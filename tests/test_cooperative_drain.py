"""Cooperative drain with SQLite and synthetic native peers, never providers."""
import asyncio
import sqlite3
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, EventCursor, OperationKey, SessionKey
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import (
    ControlOperation, LaunchIntent, NativeApprovalOperation, OpenOperation,
    OperationReceipt, RuntimeEvent, ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.native.adapter_types import RuntimeCommandNotSent
from nexus_connector_core.native.runtime_bridge import EffectFence
from nexus_connector_core.runtime import LocalRuntimeCore
from test_runtime import FakeNative, context, make_runtime, _emit_durable_native_request


async def opened(tmp_path, *, native=None, sink=None):
    runtime, journal, factory = make_runtime(tmp_path, event_sink=sink)
    if native is not None:
        factory.native = native
    authority = context(actions={'runtime.open', 'runtime.close', 'turn.submit',
                                 'turn.steer', 'turn.interrupt', 'approval.decide', 'input.provide'})
    prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), authority)
    operation = OpenOperation('open', 'session', 'epoch', prepared)
    receipt = await runtime.open(operation, authority)
    return runtime, journal, factory, authority, operation, receipt


async def finish(runtime, journal):
    await runtime.shutdown(ShutdownPolicy(0.01, 0.01))
    await journal.aclose()


async def terminal(runtime, native, operation='turn'):
    await native.queue.put(RuntimeEvent('srv', 'exe', 'session', 'epoch', 0,
        'turn_state', 'turn/completed', {'delivery_phase': 'terminal',
        'delivery_outcome': 'success', 'turn_id': 'turn-native'}, operation_id=operation))
    cursor = EventCursor('srv', 'exe', 'session', 'epoch')
    async def wait():
        while (await runtime._journal.get_receipt(OperationKey('srv', 'exe', operation))).stage != 'SUCCEEDED':
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), 2)
    return cursor


@pytest.mark.asyncio
async def test_drain_is_passive_idempotent_and_fences_only_new_work(tmp_path):
    runtime, journal, factory, auth, opening, opened_receipt = await opened(tmp_path)
    try:
        before_drain = await runtime.drain_status()
        assert before_drain['state'] == 'RUNNING' and not before_drain['quiescent']
        assert before_drain['resources'] == [] and before_drain['owned_sessions'] == []
        assert before_drain['activity_revision'] == runtime.drain_revision()
        before = await journal._run(lambda db: db.total_changes)
        runtime.begin_drain()
        runtime.begin_drain()
        assert (await runtime.drain_status())['quiescent']
        assert await journal._run(lambda db: db.total_changes) == before
        assert not runtime._shutting_down and not factory.native.stopped
        assert await runtime.open(opening, auth) == opened_receipt
        calls = [runtime.prepare(opening.prepared.intent, auth),
                 runtime.open(replace(opening, operation_id='new-open', session_id='new'), auth),
                 runtime.submit(TurnOperation('new-turn', 'session', 'private content'), auth),
                 runtime.control(ControlOperation('new-steer', 'session', 'steer', 'private content'), auth)]
        for call in calls:
            with pytest.raises(CoreError, match='RUNTIME_DRAINING'):
                await call
        assert factory.open_count == 1 and factory.native.sent == []
        assert await journal.get_receipt(OperationKey('srv', 'exe', 'new-turn')) is None
        await runtime.control(ControlOperation('interrupt', 'session', 'interrupt'), auth)
        assert factory.native.sent[-1][0] == 'interrupt'
    finally:
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_idle_native_does_not_hide_turn_or_unacknowledged_result(tmp_path):
    runtime, journal, factory, auth, _, _ = await opened(tmp_path)
    try:
        receipt = await runtime.submit(TurnOperation('turn', 'session', 'secret'), auth)
        runtime.begin_drain()
        assert not (await runtime.drain_status())['quiescent']
        assert await runtime.submit(TurnOperation('turn', 'session', 'secret'), auth) == receipt
        cursor = await terminal(runtime, factory.native)
        report = await runtime.drain_status()
        assert 'EVENT_ACK_PENDING' in {row['reason'] for row in report['resources']}
        await runtime.acknowledge_events(cursor, await journal.contiguous_watermark(cursor))
        assert (await runtime.drain_status())['quiescent']
        assert not factory.native.stopped
    finally:
        await finish(runtime, journal)


@pytest.mark.asyncio
@pytest.mark.parametrize('lost', [False, True])
async def test_admitted_native_decision_remains_available_and_lost_reply_is_unknown(tmp_path, lost):
    class Native(FakeNative):
        replies = 0

        async def reply_native_approval(self, request, decision, response):
            self.replies += 1
            if lost:
                raise RuntimeError('synthetic lost reply')

    native = Native()
    runtime, journal, _, auth, _, _ = await opened(tmp_path, native=native)
    request = {'request_id': 7, 'request_hash': 'a' * 64,
               'method': 'item/commandExecution/requestApproval',
               'params': {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'item'}}
    try:
        await _emit_durable_native_request(runtime, native, request)
        runtime.begin_drain()
        assert 'NATIVE_REQUEST_PENDING' in {row['reason'] for row in (await runtime.drain_status())['resources']}
        decision = NativeApprovalOperation('decision', 'session', request, 'accept')
        if lost:
            with pytest.raises(RuntimeError):
                await runtime.decide_native_approval(decision, auth)
        else:
            assert (await runtime.decide_native_approval(decision, auth)).stage == 'SUBMITTED'
        assert native.replies == 1 and not native.stopped
        cursor = EventCursor('srv', 'exe', 'session', 'epoch')
        await runtime.acknowledge_events(cursor, await journal.contiguous_watermark(cursor))
        result = await runtime.drain_status()
        assert result['state'] == ('UNKNOWN' if lost else 'QUIESCENT')
    finally:
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_waiting_submit_fences_before_journal_and_native_dispatch(tmp_path):
    runtime, journal, factory, auth, _, _ = await opened(tmp_path)
    binding = runtime._sessions[SessionKey('srv', 'exe', 'session')]
    try:
        await binding.normal_lock.acquire()
        task = asyncio.create_task(runtime.submit(TurnOperation('queued', 'session', 'text'), auth))
        await asyncio.sleep(0.02)
        runtime.begin_drain()
        assert not (await runtime.drain_status())['quiescent']
        binding.normal_lock.release()
        with pytest.raises(CoreError, match='RUNTIME_DRAINING'):
            await task
        assert not factory.native.sent
        assert await journal.get_receipt(OperationKey('srv', 'exe', 'queued')) is None
    finally:
        if binding.normal_lock.locked():
            binding.normal_lock.release()
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_opening_guard_fences_a_late_spawn_without_forcing_existing_work(tmp_path):
    runtime, journal, factory = make_runtime(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    captured = []

    async def opening(prepared, session_id, auth, *, stream_epoch, opening_guard):
        captured.append(opening_guard)
        entered.set()
        await release.wait()
        if opening_guard.closed:
            raise RuntimeCommandNotSent('draining', code='RUNTIME_DRAINING')
        raise AssertionError('late spawn was allowed')

    factory.open = opening
    runtime._factory_accepts_opening_guard = True
    auth = context()
    prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), auth)
    task = asyncio.create_task(runtime.open(OpenOperation('late', 'session', 'epoch', prepared), auth))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        runtime.begin_drain()
        assert captured[0].closed
        assert not (await runtime.drain_status())['quiescent']
        assert not factory.native.stopped
        release.set()
        with pytest.raises(CoreError, match='RUNTIME_DRAINING'):
            await task
        receipt = await journal.get_receipt(OperationKey('srv', 'exe', 'late'))
        assert receipt.stage == 'FAILED' and not receipt.possible_effect
    finally:
        release.set()
        await finish(runtime, journal)


@pytest.mark.parametrize('action', ['send_turn', 'steer'])
def test_native_write_fence_rechecks_drain_but_preserves_decisions(action):
    draining = False
    fence = EffectFence(productive_drain_probe=lambda: draining)
    fence.check(action)
    draining = True
    with pytest.raises(RuntimeCommandNotSent, match='draining'):
        fence.check(action)
    for allowed in ('interrupt', 'end', 'approval.decide', 'input.provide'):
        fence.check(allowed)


@pytest.mark.asyncio
async def test_legacy_unclassified_receipt_survives_upgrade_and_stays_unknown(tmp_path):
    path = tmp_path / 'legacy.db'
    journal = SQLiteJournal(path)
    key = OperationKey('srv', 'exe', 'old')
    await journal.admit(key, 'digest', 'session')
    await journal.mark_possible_effect(key)
    old = await journal.record_receipt(key, OperationReceipt('old', 'digest', 'SUBMITTED', True, False, 'session'))
    await journal.aclose()
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE operation_actions')
    journal = SQLiteJournal(path)
    runtime = LocalRuntimeCore(journal, object(), candidates={}, workspace_roots={})
    try:
        runtime.begin_drain()
        result = await runtime.drain_status()
        assert result['state'] == 'UNKNOWN'
        assert result['resources'][0]['operation_id'] == 'old'
        assert await journal.get_receipt(key) == old
        assert (await journal.drain_snapshot())['operations'][0]['action'] is None
    finally:
        await journal.aclose()


@pytest.mark.asyncio
async def test_restart_keeps_known_pending_turn_and_does_not_trust_idle(tmp_path):
    runtime, journal, factory, auth, _, _ = await opened(tmp_path)
    await runtime.submit(TurnOperation('turn', 'session', 'secret'), auth)
    # Second reader simulates recovered Core state; it never acquires native ownership.
    recovered = LocalRuntimeCore(journal, object(), candidates={}, workspace_roots={})
    try:
        recovered.begin_drain()
        result = await recovered.drain_status()
        assert not result['quiescent']
        assert 'SESSION_RECONCILIATION_PENDING' in {row['reason'] for row in result['resources']}
        assert any(row.get('operation_id') == 'turn' for row in result['resources'])
        assert not factory.native.stopped
    finally:
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_failed_sink_is_not_hidden_by_ack_or_idle(tmp_path):
    async def sink(event):
        raise RuntimeError('synthetic sink failure')

    runtime, journal, factory, auth, _, _ = await opened(tmp_path, sink=sink)
    try:
        await runtime.submit(TurnOperation('turn', 'session', 'secret'), auth)
        runtime.begin_drain()
        cursor = await terminal(runtime, factory.native)
        await runtime.acknowledge_events(cursor, await journal.contiguous_watermark(cursor))
        result = await runtime.drain_status()
        assert not result['quiescent']
        assert 'EVENT_SINK_PENDING' in {row['reason'] for row in result['resources']}
    finally:
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_unknown_stream_requires_containment_not_idle_inference(tmp_path):
    runtime, journal, factory, _, _, _ = await opened(tmp_path)
    try:
        await factory.native.queue.put(RuntimeError('synthetic stream loss'))
        binding = runtime._sessions[SessionKey('srv', 'exe', 'session')]
        await asyncio.wait_for(binding.pump, 2)
        runtime.begin_drain()
        assert (await runtime.drain_status())['state'] == 'UNKNOWN'
        assert not factory.native.stopped
        await runtime.shutdown(ShutdownPolicy(0.01, 0.01))
        assert factory.native.stopped
    finally:
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_status_cancel_and_repeat_do_not_multiply_journal_readers(tmp_path):
    runtime, journal, _, _, _, _ = await opened(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    original = journal.drain_snapshot
    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return await original()

    journal.drain_snapshot = read
    try:
        runtime.begin_drain()
        first = asyncio.create_task(runtime.drain_status())
        await entered.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(runtime.drain_status())
        await asyncio.sleep(0)
        assert calls == 1
        release.set()
        assert (await second)['quiescent']
    finally:
        release.set()
        await finish(runtime, journal)


def test_begin_drain_rejects_another_event_loop(tmp_path):
    runtime, journal, _ = make_runtime(tmp_path)

    async def first():
        runtime.begin_drain()

    async def second():
        with pytest.raises(CoreError, match='SCOPE_MISMATCH'):
            runtime.begin_drain()
    try:
        asyncio.run(first())
        asyncio.run(second())
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_pending_send_remains_owned_until_explicit_shutdown(tmp_path):
    class Native(FakeNative):
        def __init__(self):
            super().__init__()
            self.entered, self.release, self.forced = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
            if verb == 'send_turn':
                self.entered.set()
                await self.release.wait()
            await super().send(verb, payload, operation_id, expected_turn_id=expected_turn_id)

        async def force_stop(self):
            self.forced.set()
            self.stopped = True
            await self.queue.put(None)

    native = Native()
    runtime, journal, _, auth, _, _ = await opened(tmp_path, native=native)
    pending = asyncio.create_task(runtime.submit(TurnOperation('turn', 'session', 'text'), auth))
    try:
        await native.entered.wait()
        runtime.begin_drain()
        report = await runtime.drain_status()
        assert not report['quiescent']
        assert 'COMMAND_IN_FLIGHT' in {r['reason'] for r in report['resources']}
        assert not native.forced.is_set() and not native.stopped
        shutdown = asyncio.create_task(runtime.shutdown(ShutdownPolicy(0.01, 0.01)))
        await asyncio.wait_for(native.forced.wait(), 2)
        assert not pending.done()
        assert (await journal.owned_slot_state(SessionKey('srv', 'exe', 'session'))) != 'released'
        native.release.set()
        await pending
        await shutdown
    finally:
        native.release.set()
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_cancelled_open_stays_unknown_without_drain_starting_containment(tmp_path):
    runtime, journal, factory = make_runtime(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def opening(prepared, session_id, auth, *, stream_epoch):
        entered.set()
        await release.wait()
        return factory.native

    factory.open = opening
    auth = context()
    prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), auth)
    pending = asyncio.create_task(runtime.open(OpenOperation('lost', 'session', 'epoch', prepared), auth))
    try:
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        runtime.begin_drain()
        report = await runtime.drain_status()
        assert report['state'] == 'UNKNOWN'
        assert not factory.native.stopped
        assert (await journal.get_receipt(OperationKey('srv', 'exe', 'lost'))).stage == 'OUTCOME_UNKNOWN'
    finally:
        release.set()
        await asyncio.sleep(0.02)
        await finish(runtime, journal)


@pytest.mark.asyncio
async def test_bounded_journal_read_never_calls_overflow_empty(tmp_path):
    journal = SQLiteJournal(tmp_path / 'bounded.db')
    runtime = LocalRuntimeCore(journal, object(), candidates={}, workspace_roots={})
    try:
        for index in range(257):
            await journal.admit(OperationKey('srv', 'exe', f'op-{index:03}'), 'digest', 'session')
        runtime.begin_drain()
        result = await runtime.drain_status()
        assert result['state'] == 'UNKNOWN' and not result['quiescent']
        assert len(result['resources']) == 256
        assert result['resources'][-1]['reason'] == 'RESOURCE_LIMIT'
    finally:
        await journal.aclose()


@pytest.mark.asyncio
async def test_codex_steer_tracks_existing_turn_without_inventing_second_terminal(tmp_path):
    runtime, journal, factory, auth, _, _ = await opened(tmp_path)
    try:
        await runtime.submit(TurnOperation('turn', 'session', 'initial'), auth)
        await runtime.control(ControlOperation('steer', 'session', 'steer', 'amendment',
                                              expected_turn_id='turn-native'), auth)
        runtime.begin_drain()
        assert not (await runtime.drain_status())['quiescent']
        cursor = await terminal(runtime, factory.native)
        await runtime.acknowledge_events(cursor, await journal.contiguous_watermark(cursor))
        assert (await runtime.drain_status())['quiescent']
        assert (await journal.get_receipt(OperationKey('srv', 'exe', 'steer'))).stage == 'SUBMITTED'
    finally:
        await finish(runtime, journal)
