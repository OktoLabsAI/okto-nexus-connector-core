"""Public composition of distinct Core owners sharing a real SQLite journal."""
import copy

import pytest

from nexus_connector_core import combine_drain_status, OperationKey
from nexus_connector_core.models import ControlOperation, LaunchIntent, OpenOperation, OperationReceipt, ShutdownPolicy
from nexus_connector_core.runtime import LocalRuntimeCore
from test_runtime import FakeFactory, context, make_runtime


async def siblings(tmp_path):
    first, journal, _ = make_runtime(tmp_path)
    second = LocalRuntimeCore(journal, FakeFactory(), candidates=first._candidates,
                              workspace_roots=first._workspace_roots)
    auth = context()
    for index, runtime in enumerate((first, second)):
        prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), auth)
        await runtime.open(OpenOperation(f'open-{index}', f'session-{index}', f'epoch-{index}', prepared), auth)
    first.begin_drain()
    second.begin_drain()
    return first, second, journal, auth


async def cleanup(first, second, journal):
    for runtime in (first, second):
        await runtime.shutdown(ShutdownPolicy(0.01, 0.01))
    await journal.aclose()


@pytest.mark.asyncio
async def test_two_idle_owners_resolve_only_exact_shared_journal_claims(tmp_path):
    first, second, journal, _ = await siblings(tmp_path)
    try:
        reports = [await first.drain_status(), await second.drain_status()]
        assert all(report['state'] == 'UNKNOWN' for report in reports)
        assert all({row['reason'] for row in report['resources']} == {'SESSION_RECONCILIATION_PENDING'}
                   for report in reports)
        result = combine_drain_status(reports)
        assert result == {'state': 'QUIESCENT', 'quiescent': True, 'resources': []}
        assert all(runtime.drain_revision() == report['activity_revision']
                   for runtime, report in zip((first, second), reports))
    finally:
        await cleanup(first, second, journal)


@pytest.mark.asyncio
async def test_orphan_claim_is_not_resolved_by_unrelated_live_owners(tmp_path):
    first, second, journal, _ = await siblings(tmp_path)
    try:
        key = OperationKey('srv', 'exe', 'orphan-opening')
        await journal.admit(key, 'digest', 'orphan', claim_session=True, action='runtime.open')
        await journal.mark_possible_effect(key)
        await journal.record_receipt(key, OperationReceipt(key.operation_id, 'digest', 'SUBMITTED', True, False, 'orphan'))
        result = combine_drain_status([await first.drain_status(), await second.drain_status()])
        assert result['state'] == 'UNKNOWN' and not result['quiescent']
        assert {row['session_id'] for row in result['resources']} == {'orphan'}
        assert all(row['opening_operation_id'] == 'orphan-opening' for row in result['resources'])
    finally:
        await cleanup(first, second, journal)


@pytest.mark.asyncio
async def test_current_revision_detects_a_control_between_awaited_reports(tmp_path):
    first, second, journal, auth = await siblings(tmp_path)
    try:
        earlier = await first.drain_status()
        await first.control(ControlOperation('interrupt', 'session-0', 'interrupt'), auth)
        later = await second.drain_status()
        # A pure combination cannot establish time. The public synchronous
        # check deliberately rejects this otherwise empty technical inventory.
        assert combine_drain_status([earlier, later])['quiescent']
        assert first.drain_revision() != earlier['activity_revision']
        refreshed = [await first.drain_status(), await second.drain_status()]
        assert combine_drain_status(refreshed)['quiescent']
        assert all(runtime.drain_revision() == report['activity_revision']
                   for runtime, report in zip((first, second), refreshed))
    finally:
        await cleanup(first, second, journal)


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['opening', 'namespace', 'duplicate', 'missing_revision', 'missing_owners'])
async def test_composition_does_not_guess_missing_or_ambiguous_ownership(tmp_path, mutation):
    first, second, journal, _ = await siblings(tmp_path)
    try:
        reports = copy.deepcopy([await first.drain_status(), await second.drain_status()])
        if mutation == 'opening':
            reports[1]['owned_sessions'][0]['opening_operation_id'] = 'another-opening'
        elif mutation == 'namespace':
            reports[1]['owned_sessions'][0]['server_id'] = 'another-server'
        elif mutation == 'duplicate':
            reports.append(copy.deepcopy(reports[1]))
        elif mutation == 'missing_revision':
            reports[1].pop('activity_revision')
        else:
            reports[1].pop('owned_sessions')
        result = combine_drain_status(reports)
        assert result['state'] == 'UNKNOWN' and not result['quiescent']
    finally:
        await cleanup(first, second, journal)
