"""Only an exact fenced, settled and released local launch can drain without a stream."""
import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, EventCursor, LaunchIntent, OpenOperation, OperationKey, SessionKey, ShutdownPolicy
from nexus_connector_core.models import RuntimeEvent
from nexus_connector_core.runtime import LocalRuntimeCore, _SessionTombstones
from test_runtime import FakeFactory, context, make_runtime
from test_uncertain_launch_shutdown import stopped

KEY = SessionKey('srv', 'exe', 'session')
OPEN = OperationKey('srv', 'exe', 'open')


async def failed_open(tmp_path):
    runtime, journal, factory = make_runtime(tmp_path, cleanup_budget_seconds=.01)
    async def refuse(prepared, session_id, ctx, *, stream_epoch, process_launch):
        # The planned producer was durably admitted, but never claims spawn.
        raise CoreError('AUTH_EXPIRED', 'synthetic_materialization')
    factory.open = refuse
    runtime._factory_accepts_process_launch = True
    ctx = context()
    prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), ctx)
    with pytest.raises(CoreError, match='AUTH_EXPIRED'):
        await runtime.open(OpenOperation('open', 'session', 'epoch', prepared), ctx)
    return runtime, journal


async def finish(runtime, journal):
    await runtime.shutdown(ShutdownPolicy(.1, .1))
    await journal.aclose()


@pytest.mark.asyncio
async def test_never_claimed_release_drains_without_rewriting_claim_or_receipt(tmp_path):
    runtime, journal = await failed_open(tmp_path)
    try:
        await stopped(runtime, KEY)
        receipt = await journal.get_receipt(OPEN)
        assert receipt.stage == 'FAILED' and receipt.possible_effect and not receipt.retry_safe
        assert (await journal.get_process_launch(KEY)).stop_proof == 'NEVER_CLAIMED'
        assert (await journal.owned_slot_state(KEY)).released
        assert await journal.get_process_birth(KEY) is None
        facts = await journal.drain_snapshot()
        assert facts['claims'][0]['stream_epoch'] is None
        assert facts['streams'] == facts['watermarks'] == []
        before = await journal._run(lambda db: (db.total_changes, tuple(db.iterdump())))
        runtime.begin_drain()
        report = await runtime.drain_status()
        assert report['state'] == 'QUIESCENT' and not report['resources']
        assert report['released_sessions'] == []  # No cross-owner stream proof invented.
        assert runtime.drain_revision() == report['activity_revision']
        assert await journal._run(lambda db: (db.total_changes, tuple(db.iterdump()))) == before
        assert await journal.get_receipt(OPEN) == receipt
    finally:
        await finish(runtime, journal)


@pytest.mark.asyncio
@pytest.mark.parametrize('release_fault', ['blocked', 'refused'])
async def test_release_proof_waits_for_exact_durable_completion(tmp_path, monkeypatch, release_fault):
    runtime, journal = await failed_open(tmp_path)
    original = journal.release_owned_slot
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def held(*args):
        calls.append(args)
        entered.set()
        if release_fault == 'blocked':
            await release.wait()
        elif len(calls) == 1:
            raise OSError('Synthetic refusal before commit')
        return await original(*args)
    monkeypatch.setattr(journal, 'release_owned_slot', held)
    try:
        await runtime.shutdown(ShutdownPolicy(.01, .01))
        await asyncio.wait_for(entered.wait(), 3)
        runtime.begin_drain()
        assert not (await runtime.drain_status())['quiescent']
        assert runtime._session_tombstones.released_proof(KEY) is None
        if release_fault == 'blocked':
            await runtime.shutdown(ShutdownPolicy(0, 0))
            assert len(calls) == 1
        release.set()
        await stopped(runtime, KEY)
        assert (await runtime.drain_status())['quiescent']
        assert (await journal.owned_slot_state(KEY)).released
    finally:
        release.set()
        await finish(runtime, journal)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['restart', 'evicted', 'no_proof', 'opening', 'connection', 'owner',
    'stream', 'ambiguous_acked_streams', 'missing_generation', 'claimed', 'unfenced'])
async def test_absent_stream_is_never_a_generic_release_proof(tmp_path, change):
    runtime, journal = await failed_open(tmp_path)
    other = None
    try:
        runtime._session_tombstones = _SessionTombstones(1)
        await stopped(runtime, KEY)
        runtime.begin_drain()
        assert (await runtime.drain_status())['quiescent']
        if change == 'restart':
            other = LocalRuntimeCore(journal, FakeFactory(), candidates=runtime._candidates,
                workspace_roots=runtime._workspace_roots)
            other.begin_drain()
        elif change == 'evicted':
            runtime._session_tombstones.record(SessionKey('srv', 'exe', 'other'), 'unknown')
        elif change == 'no_proof':
            runtime._session_tombstones.record(KEY, 'released')
        elif change in ('stream', 'ambiguous_acked_streams'):
            epochs = ['late-stream'] if change == 'stream' else ['late-one', 'late-two']
            for epoch in epochs:
                await journal.append_event(RuntimeEvent('srv','exe','session',epoch,1,
                    'tool_activity','synthetic',{}))
                await runtime.acknowledge_events(EventCursor('srv','exe','session',epoch), 1)
        elif change == 'missing_generation':
            await journal._run(lambda db: db.execute('DELETE FROM session_open_generations'))
        elif change in ('claimed', 'unfenced'):
            proof = runtime._session_tombstones.released_proof(KEY)
            mutation = dict(spawn_claimed=True, stop_proof='CONTAINER_STOPPED') if change == 'claimed' else dict(producer_fenced=False)
            runtime._session_tombstones.record(KEY, 'released', replace(proof, record=replace(proof.record, **mutation)))
        else:
            proof = runtime._session_tombstones.released_proof(KEY)
            field, value = {'opening': ('opening_operation_id', 'other'),
                'connection': ('connection_generation', 99), 'owner': ('owner_generation', 99)}[change]
            runtime._session_tombstones.record(KEY, 'released', replace(proof,
                record=replace(proof.record, identity=replace(proof.record.identity, **{field:value}))))
        report = await (other or runtime).drain_status()
        assert not report['quiescent']
        assert 'SESSION_RECONCILIATION_PENDING' in {r['reason'] for r in report['resources']}
    finally:
        if other is not None:
            await other.shutdown(ShutdownPolicy(.01,.01))
        await finish(runtime, journal)
