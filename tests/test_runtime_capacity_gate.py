"""Capacity must gate actual native sends, not merely a read model."""
import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import (CapacityConsumption, CoreError, OperationKey, OperationCapacityDeferred,
                                  SQLiteOwnedSlotLedger)
from nexus_connector_core.models import (LaunchIntent, OpenOperation, Operation,
    RuntimeEvent, ShutdownPolicy, TurnOperation, ControlOperation, EffectNotSent)
from nexus_connector_core.protocol import intent_hash
from test_capacity_contract import request
from test_runtime import context, make_runtime
from test_capacity_slot_ledger import bind_consumption


def scoped_request(ctx, unit='next_turn'):
    req = request(unit)
    return replace(req, scope=replace(req.scope, server_id=ctx.server_id,
        executor_id=ctx.executor_id, workspace_id=ctx.workspace_id,
        connection_generation=ctx.connection_generation,
        authorization_revision=ctx.authorization_revision,
        configuration_revision=ctx.configuration_revision))


async def open_session(runtime, ctx):
    prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), ctx)
    return await runtime.open(OpenOperation('open', 'session', 'epoch', prepared), ctx)


async def terminal(factory, operation_id):
    await factory.native.queue.put(RuntimeEvent('srv', 'exe', 'session', 'epoch', 0,
        'turn_state', 'turn/completed', {'delivery_phase': 'terminal', 'turn_id': operation_id}, operation_id))


def test_send_return_does_not_free_turn_but_correlated_terminal_does(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        runtime, journal, factory = make_runtime(tmp_path, owned_slot_ledger=ledger, capacity_enabled=True)
        ctx = context()
        try:
            await open_session(runtime, ctx)
            assert (await runtime.submit(TurnOperation('one', 'session', 'hello'), ctx)).stage == 'SUBMITTED'
            assert factory.native.sent == [('send_turn', {'text': 'hello'}, 'one')]
            with pytest.raises(OperationCapacityDeferred) as refused:
                await runtime.submit(TurnOperation('two', 'session', 'second'), ctx)
            assert refused.value.key == OperationKey('srv', 'exe', 'two')
            assert refused.value.retry_safe and not refused.value.possible_effect
            assert refused.value.intent_hash == intent_hash(Operation('two', 'session', 'turn.submit', {'text': 'second'}), ctx)
            # Refusal precedes journal admission, so the same operation can wait.
            assert await journal.get_receipt(OperationKey('srv', 'exe', 'two')) is None
            await runtime.control(ControlOperation('interrupt', 'session', 'interrupt'), ctx)
            assert factory.native.sent[-1][0] == 'interrupt'
            await terminal(factory, 'unrelated')
            await asyncio.sleep(0.03)
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await runtime.submit(TurnOperation('two', 'session', 'second'), ctx)
            await terminal(factory, 'one')
            async def after_terminal():
                while True:
                    try:
                        return await runtime.submit(TurnOperation('two', 'session', 'second'), ctx)
                    except CoreError as error:
                        if error.code != 'CAPACITY_EXCEEDED':
                            raise
                        await asyncio.sleep(0.005)
            assert (await asyncio.wait_for(after_terminal(), 2)).stage == 'SUBMITTED'
            assert [x[2] for x in factory.native.sent] == ['one', 'interrupt', 'two']
            assert (await runtime.submit(TurnOperation('one', 'session', 'hello'), ctx)).stage == 'SUBMITTED'
            assert [x[2] for x in factory.native.sent] == ['one', 'interrupt', 'two']
        finally:
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0, interrupt_seconds=0))
            journal.close()
            ledger.close()
    asyncio.run(run())


def test_real_submit_cannot_steal_reserved_first_turn(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        runtime, journal, factory = make_runtime(tmp_path, owned_slot_ledger=ledger, capacity_enabled=True)
        ctx = context()
        req = scoped_request(ctx)
        try:
            await open_session(runtime, ctx)
            held = await ledger.reserve_capacity_slot(req, now=10, boot_id='boot-1')
            ordinary = TurnOperation('ordinary', 'session', 'must wait')
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await runtime.submit(ordinary, ctx)
            selected = Operation('winner', 'session', 'turn.submit', {'text': 'selected'})
            consumption = CapacityConsumption('winner', intent_hash(selected, ctx), None, None)
            await ledger.consume_capacity_slot(req, held.reservation_id, consumption, now=10, boot_id='boot-1')
            await bind_consumption(ledger, req, held, consumption)
            await runtime.submit(TurnOperation('winner', 'session', 'selected'), ctx)
            assert factory.native.sent == [('send_turn', {'text': 'selected'}, 'winner')]
            assert await journal.get_receipt(OperationKey('srv', 'exe', 'ordinary')) is None
        finally:
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0, interrupt_seconds=0))
            journal.close()
            ledger.close()
    asyncio.run(run())


def test_refused_open_does_not_poison_winner_journal_claim(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        runtime, journal, factory = make_runtime(tmp_path, owned_slot_ledger=ledger, capacity_enabled=True)
        ctx = context()
        req = scoped_request(ctx, 'new_session')
        try:
            prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), ctx)
            held = await ledger.reserve_capacity_slot(req, now=10, boot_id='boot-1')
            with pytest.raises(OperationCapacityDeferred):
                await runtime.open(OpenOperation('loser-open', 'session', 'epoch', prepared), ctx)
            assert factory.open_count == 0
            assert await journal.get_receipt(OperationKey('srv', 'exe', 'loser-open')) is None
            opening = Operation('winner-open', 'session', 'runtime.open', {
                'adapter_id': prepared.intent.adapter_id, 'profile_fingerprint': prepared.profile_fingerprint,
                'root_fingerprint': prepared.root_fingerprint, 'stream_epoch': 'epoch'})
            turn = Operation('winner-turn', 'session', 'turn.submit', {'text': 'selected'})
            c = CapacityConsumption(turn.operation_id, intent_hash(turn, ctx),
                                    opening.operation_id, intent_hash(opening, ctx))
            await ledger.consume_capacity_slot(req, held.reservation_id, c, now=10, boot_id='boot-1')
            await bind_consumption(ledger, req, held, c)
            await runtime.open(OpenOperation('winner-open', 'session', 'epoch', prepared), ctx)
            assert factory.open_count == 1
            assert len((await ledger.owned_slot_page()).reservations) == 1
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await runtime.submit(TurnOperation('ordinary', 'session', 'must wait'), ctx)
            await runtime.submit(TurnOperation('winner-turn', 'session', 'selected'), ctx)
            assert factory.native.sent == [('send_turn', {'text': 'selected'}, 'winner-turn')]
        finally:
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0, interrupt_seconds=0))
            journal.close()
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('uncertain', [False, True])
def test_send_failure_releases_only_when_proven_no_effect(tmp_path, uncertain):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        runtime, journal, factory = make_runtime(tmp_path, owned_slot_ledger=ledger, capacity_enabled=True)
        ctx = context()
        try:
            await open_session(runtime, ctx)
            original_send = factory.native.send
            async def failed_send(*args, **kwargs):
                if uncertain:
                    raise OSError('ambiguous native write')
                raise EffectNotSent('refused before write')
            factory.native.send = failed_send
            with pytest.raises((CoreError, OSError)):
                await runtime.submit(TurnOperation('one', 'session', 'first'), ctx)
            factory.native.send = original_send
            if uncertain:
                with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                    await runtime.submit(TurnOperation('two', 'session', 'second'), ctx)
                assert factory.native.sent == []
            else:
                await runtime.submit(TurnOperation('two', 'session', 'second'), ctx)
                assert factory.native.sent[0][2] == 'two'
        finally:
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0, interrupt_seconds=0))
            journal.close()
            ledger.close()
    asyncio.run(run())
