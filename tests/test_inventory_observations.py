"""Partial observations must neither invent absence nor refresh stale siblings."""
from copy import deepcopy
from dataclasses import replace

import pytest

from nexus_connector_core import (CoreError, build_executor_inventory_snapshot,
    calculate_inventory_revision, inventory_observation_fresh,
    verify_executor_inventory_snapshot)
from nexus_connector_core.executor_inventory import _revision
from test_executor_inventory import _candidate


def pending():
    return {adapter: dict(state='PENDING', observation_age_ms=None, error_code=None)
            for adapter in ('claude_stream', 'codex_app_server', 'pi_rpc')}


def completed(state='PRESENT', age=0):
    return dict(state=state, observation_age_ms=age, error_code=None)


def snapshot(candidates=(), observations=None, *, age=0, sequence=1):
    return build_executor_inventory_snapshot(candidates, observations=observations,
        server_id='server', executor_id='host', producer_instance_id='owner',
        publication_sequence=sequence, observation_age_ms=age)


def test_pending_and_failed_are_not_reported_as_missing_installations(tmp_path):
    observations = pending()
    candidate = replace(_candidate(str(tmp_path/'claude')), adapter_id='claude_stream')
    observations['claude_stream'] = completed()
    observations['pi_rpc'] = dict(state='FAILED', observation_age_ms=None, error_code='PROFILE_DRIFT')
    value = snapshot((candidate,), observations)
    assert value['snapshot_format_version'] == 3
    assert [row['adapter_id'] for row in value['availability']['availability']] == ['claude_stream']
    assert [row['adapter_id'] for row in value['evidence']] == ['claude_stream']
    assert inventory_observation_fresh(value, 'claude_stream')
    assert not inventory_observation_fresh(value, 'pi_rpc')
    assert not inventory_observation_fresh(value, 'codex_app_server')
    assert not inventory_observation_fresh(value, 'unknown')
    assert str(tmp_path) not in str(value)
    assert calculate_inventory_revision((candidate,), observations=observations) == value['inventory_revision']


def test_absence_requires_a_completed_observation():
    waiting = snapshot(observations=pending())
    assert waiting['availability']['availability'] == []
    assert not inventory_observation_fresh(waiting, 'pi_rpc')
    observed = snapshot()
    assert all(row['state'] == 'ABSENT' for row in observed['observations'])
    assert all(row['state'] == 'NOT_INSTALLED' for row in observed['availability']['availability'])
    assert inventory_observation_fresh(observed, 'pi_rpc')
    assert observed['evidence'] == []  # Fresh absence never authorizes an installation.
    assert waiting['inventory_revision'] != observed['inventory_revision']


def test_another_harness_publication_cannot_refresh_old_evidence(tmp_path):
    first = _candidate(str(tmp_path/'codex'))
    second = replace(_candidate(str(tmp_path/'claude')), adapter_id='claude_stream')
    observations = pending()
    observations['codex_app_server'] = completed(age=118000)
    observations['claude_stream'] = completed()
    before = snapshot((first, second), observations, age=1000)
    assert inventory_observation_fresh(before, 'codex_app_server', elapsed_ms=999)
    assert not inventory_observation_fresh(before, 'codex_app_server', elapsed_ms=1000)
    observations['codex_app_server']['observation_age_ms'] = 120000
    after = snapshot((first, second), observations, sequence=2)
    assert inventory_observation_fresh(after, 'claude_stream')
    assert not inventory_observation_fresh(after, 'codex_app_server')
    assert before['inventory_revision'] == after['inventory_revision']


def test_failure_transition_changes_semantics_but_age_does_not():
    observations = pending()
    before = snapshot(observations=observations)
    observations['pi_rpc'] = dict(state='FAILED', observation_age_ms=None, error_code='BINARY_NOT_FOUND')
    after = snapshot(observations=observations)
    assert before['inventory_revision'] != after['inventory_revision']


@pytest.mark.parametrize('mutation', [
    'omit', 'duplicate', 'unknown', 'unsorted', 'extra', 'pending_age', 'pending_error',
    'failed_without_error', 'failed_with_path', 'failed_with_age', 'bool_age', 'negative_age',
    'too_old', 'absent_with_candidate', 'pending_with_candidate', 'present_without_candidate',
    'missing_availability', 'pending_availability', 'fake_absent_availability',
])
def test_forged_coverage_refused_even_with_recomputed_revision(tmp_path, mutation):
    candidate = _candidate(str(tmp_path/'codex'))
    value = snapshot((candidate,))
    rows = value['observations']
    codex = next(row for row in rows if row['adapter_id'] == 'codex_app_server')
    pi = next(row for row in rows if row['adapter_id'] == 'pi_rpc')
    if mutation == 'omit': rows.pop()
    elif mutation == 'duplicate': rows.append(deepcopy(rows[0]))
    elif mutation == 'unknown': pi['adapter_id'] = 'unknown'
    elif mutation == 'unsorted': rows.reverse()
    elif mutation == 'extra': pi['path'] = 'forbidden'
    elif mutation == 'pending_age': pi['state'] = 'PENDING'
    elif mutation == 'pending_error': pi.update(state='PENDING', observation_age_ms=None, error_code='FAILED')
    elif mutation == 'failed_without_error': pi.update(state='FAILED', observation_age_ms=None)
    elif mutation == 'failed_with_path': pi.update(state='FAILED', observation_age_ms=None, error_code='C:/secret')
    elif mutation == 'failed_with_age': pi.update(state='FAILED', error_code='PROFILE_DRIFT')
    elif mutation == 'bool_age': pi['observation_age_ms'] = True
    elif mutation == 'negative_age': pi['observation_age_ms'] = -1
    elif mutation == 'too_old': pi['observation_age_ms'] = 300001
    elif mutation == 'absent_with_candidate': codex['state'] = 'ABSENT'
    elif mutation == 'pending_with_candidate': codex.update(state='PENDING', observation_age_ms=None)
    elif mutation == 'present_without_candidate': pi['state'] = 'PRESENT'
    elif mutation == 'missing_availability': value['availability']['availability'] = []
    elif mutation == 'pending_availability': pi.update(state='PENDING', observation_age_ms=None)
    elif mutation == 'fake_absent_availability':
        next(row for row in value['availability']['availability'] if row['adapter_id']=='pi_rpc')['state'] = 'READY_FOR_RUNTIME'
    value['inventory_revision'] = _revision(value)
    with pytest.raises(CoreError) as refused:
        verify_executor_inventory_snapshot(value)
    assert refused.value.code == 'VALIDATION_ERROR'


@pytest.mark.parametrize('mutation', ['missing_adapter', 'wrong_adapter_key', 'missing_field', 'extra_field'])
def test_builder_requires_explicit_complete_coverage(mutation):
    observations = pending()
    if mutation == 'missing_adapter': observations.pop('pi_rpc')
    elif mutation == 'wrong_adapter_key': observations['pi_rpc']['adapter_id'] = 'claude_stream'
    elif mutation == 'missing_field': observations['pi_rpc'].pop('error_code')
    else: observations['pi_rpc']['credentials'] = 'not-allowed'
    with pytest.raises(CoreError) as refused:
        snapshot(observations=observations)
    assert refused.value.code == 'VALIDATION_ERROR'


def test_v2_is_readable_as_history_but_cannot_be_used_for_new_freshness():
    historical = snapshot()
    historical.pop('observations')
    historical['snapshot_format_version'] = 2
    historical['inventory_revision'] = _revision(historical)
    verify_executor_inventory_snapshot(historical, allow_historical=True)
    with pytest.raises(CoreError):
        verify_executor_inventory_snapshot(historical)
    with pytest.raises(CoreError):
        inventory_observation_fresh(historical, 'pi_rpc')


@pytest.mark.parametrize('arguments', [dict(elapsed_ms=-1), dict(elapsed_ms=True),
    dict(elapsed_ms=0.1), dict(ttl_ms=0), dict(ttl_ms=True)])
def test_invalid_receipt_time_cannot_extend_freshness(arguments):
    with pytest.raises(ValueError):
        inventory_observation_fresh(snapshot(), 'pi_rpc', **arguments)


@pytest.mark.parametrize('kind', ['hello', 'welcome'])
def test_handshake_requires_peers_to_consume_the_new_observation_format(kind):
    from nexus_connector_core import R4_CONTRACT_REVISION, encode_r4_frame, decode_r4_frame
    frame = dict(protocol_major=1, contract_revision=R4_CONTRACT_REVISION,
        type=kind, server_id='server', executor_id='host', link_attempt_id='attempt',
        management_revision='nexus-connections-2026-09-29-r4', control_capabilities=[])
    if kind == 'hello':
        frame.update(core_version='0.0.12', supported_nxl=[R4_CONTRACT_REVISION], snapshot_formats=[3])
    else:
        frame.update(connection_id='connection', connection_generation=1,
                     accepted_nxl=R4_CONTRACT_REVISION, snapshot_format=3)
    assert decode_r4_frame(encode_r4_frame(frame)) == frame
    frame.update(dict(snapshot_formats=[2]) if kind == 'hello' else dict(snapshot_format=2))
    with pytest.raises(CoreError) as refused:
        encode_r4_frame(frame)
    assert refused.value.code == 'VALIDATION_ERROR'
