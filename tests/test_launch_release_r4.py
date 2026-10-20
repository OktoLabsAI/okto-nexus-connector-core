"""Never-started wire proof is distinct from process exit and receipt outcome."""
from copy import deepcopy
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, R4_PREVIEW_REVISION, decode_r4_frame, encode_r4_frame
from nexus_connector_core.launch_release_r4 import (
    project_r4_unstarted_release, validate_unstarted_release, launch_recovery_schema_validator,
)
from nexus_connector_core.process_launch import ProcessLaunchRecord
from nexus_connector_core.receipt_binding_r4 import project_r4_bound_receipt
from nexus_connector_core.models import OperationKey
from test_process_launch_storage import identity
from test_r4_resource_release import release


def projected(release, *, marked=True):
    binding, claim, slot, receipt = release
    launch = ProcessLaunchRecord(replace(identity(), key=claim.key,
        opening_operation_id=claim.opening_operation_id, connection_generation=1, owner_generation=1),
        revision=3, producer_fenced=True, stop_proof='NEVER_CLAIMED')
    receipt = replace(receipt, stage='FAILED', possible_effect=marked, retry_safe=not marked,
                      error_code='PROCESS_LAUNCH_FENCED')
    fact = project_r4_unstarted_release(binding, claim, slot, receipt, launch, journal_slot=slot, birth=None)
    opening = project_r4_bound_receipt(binding, receipt,
        key=OperationKey(claim.key.server_id, claim.key.executor_id, claim.opening_operation_id), receipt_revision=2)
    return fact, opening, launch, receipt


def report(fact):
    return dict(protocol_major=1, contract_revision=R4_PREVIEW_REVISION, type='reconcile.report',
        server_id='server', executor_id='executor', connection_id='replacement', connection_generation=2,
        reconcile_id='cycle', cursor=None, next_cursor=None, complete=True, receipts=[],
        claims=[dict(session_id='session', owner_generation=1, state='RELEASED')],
        ownership_facts=[fact], stream_watermarks=[], launch_recovery_supported=True)


@pytest.mark.parametrize('marked', [False, True])
def test_independent_never_started_proof_preserves_receipt_outcome(release, marked):
    fact, opening, launch, receipt = projected(release, marked=marked)
    assert validate_unstarted_release(fact, opening, connection_generation=2) == launch
    assert opening['possible_effect'] is marked and opening['retry_safe'] is not marked
    assert fact['process_state'] == 'NOT_STARTED' and receipt.stage == 'FAILED'
    assert decode_r4_frame(encode_r4_frame(report(fact))) == report(fact)
    binding, claim, _, _ = release
    assert project_r4_unstarted_release(binding, claim, None, receipt, launch,
        journal_slot=None, birth=None) == fact


@pytest.mark.parametrize('fault', ['unfenced', 'claimed', 'container_stop', 'revision', 'foreign',
    'digest', 'native_id', 'success', 'same_generation', 'wrong_operation', 'wrong_intent', 'wrong_owner'])
def test_unproven_or_contradictory_fact_is_refused(release, fault):
    fact, opening, _, _ = projected(release)
    generation = 2
    proof = fact['launch_proof']
    if fault == 'unfenced': proof['producer_fenced'] = False
    elif fault == 'claimed': proof['spawn_claimed'] = True
    elif fault == 'container_stop': proof['stop_proof'] = 'CONTAINER_STOPPED'
    elif fault == 'revision': proof['revision'] = 2
    elif fault == 'foreign': proof['identity']['key']['executor_id'] = 'foreign'
    elif fault == 'digest': fact['proof_digest'] = 'sha256:' + '0'*64
    elif fault == 'native_id': opening['native_id'] = 'native'
    elif fault == 'success': opening['stage'] = 'SUCCEEDED'
    elif fault == 'same_generation': generation = 1
    elif fault == 'wrong_operation': opening['operation_id'] = 'foreign'
    elif fault == 'wrong_intent': opening['intent_hash'] = 'sha256:' + '0'*64
    elif fault == 'wrong_owner': fact['owner_generation'] = 2
    with pytest.raises(CoreError):
        validate_unstarted_release(fact, opening, connection_generation=generation)


@pytest.mark.parametrize('fault', ['no_extension', 'false_extension', 'foreign_host', 'same_generation',
    'missing_proof', 'exited_with_proof', 'extra_proof_field'])
def test_codec_enforces_extension_and_exact_scope(release, fault):
    frame = report(projected(release)[0])
    if fault == 'no_extension': del frame['launch_recovery_supported']
    elif fault == 'false_extension': frame['launch_recovery_supported'] = False
    elif fault == 'foreign_host': frame['executor_id'] = 'foreign'
    elif fault == 'same_generation': frame['connection_generation'] = 1
    elif fault == 'missing_proof': del frame['ownership_facts'][0]['launch_proof']
    elif fault == 'exited_with_proof': frame['ownership_facts'][0]['process_state'] = 'EXITED'
    elif fault == 'extra_proof_field': frame['ownership_facts'][0]['launch_proof']['pid'] = 1234
    with pytest.raises(CoreError):
        encode_r4_frame(frame)


def test_extension_composes_preopen_without_mutating_base_contract(release):
    from nexus_connector_core.frame_codec_r4 import _resources, verify_r4_bundle
    original, manifest = deepcopy(_resources()[0].schema), verify_r4_bundle()
    launch_recovery_schema_validator(preopen=True)
    fact = projected(release)[0]
    encode_r4_frame(report(fact))
    assert _resources()[0].schema == original and verify_r4_bundle() == manifest


@pytest.mark.parametrize('fault', ['journal_slot', 'physical_slot', 'birth'])
def test_projection_requires_no_birth_and_all_existing_slots_released(release, fault):
    binding, claim, slot, _ = release
    _, _, launch, receipt = projected(release)
    with pytest.raises(CoreError):
        project_r4_unstarted_release(binding, claim,
            replace(slot, released=False) if fault == 'physical_slot' else slot, receipt, launch,
            journal_slot=replace(slot, released=False) if fault == 'journal_slot' else slot,
            birth=object() if fault == 'birth' else None)
