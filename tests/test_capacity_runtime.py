"""Public facade against real Core readiness and the shared durable adapter."""
import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import (
    ExecutionCapacity, CapacityScope, CapacityRequest, CapacityConsumption,
    CAPACITY_CONTRACT_REVISION, CoreError, SQLiteOwnedSlotLedger, SessionKey,
    prepare_r4_receipt_binding, TurnOperation, ShutdownPolicy, LaunchIntent, OpenOperation,
)
from test_capacity_contract import request, consumed
from test_capacity_slot_ledger import receipt_binding
from test_runtime import FakeClock, make_runtime
from test_r4_runtime_leases import attempt, grant, operation, open_session


class Authority:
    def __init__(self):
        self.reason = 'AVAILABLE'
        self.calls = []
        self.hook = None

    async def check_capacity_scope(self, request, *, action):
        self.calls.append(action)
        if self.hook:
            return await self.hook(request, action)
        return self.reason


def facade(ledger, *, authority=None, runtime=None, clock=None, boot='boot-1'):
    return ExecutionCapacity(ledger, authority=authority or Authority(),
        runtime_lookup=lambda key: runtime, boot_id=boot, clock=clock or FakeClock(10))


def capacity_request(lease_attempt, unit='next_turn'):
    return CapacityRequest(CAPACITY_CONTRACT_REVISION, 'capacity-attempt',
        CapacityScope(**lease_attempt.scope, connection_generation=lease_attempt.connection_generation,
                      boot_id='capacity-owner-boot'), unit, 'sha256:' + 'a' * 64, 10_000)


def test_public_reserve_never_launches_and_replay_is_immutable(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        authority, clock = Authority(), FakeClock(10)
        service = facade(ledger, authority=authority, clock=clock)
        req = request('new_session')
        try:
            assert (await service.assess_capacity(req)).available
            held = await service.try_reserve_capacity(req)
            clock.advance(2)
            replay = await service.try_reserve_capacity(req)
            assert replay.reservation_id == held.reservation_id
            assert replay.remaining_ms == 8000
            assert len((await ledger.owned_slot_page()).reservations) == 1
            assert (await service.get_capacity_reservation(req)).reservation_id == held.reservation_id
            assert (await service.release_capacity(req, held.reservation_id, 'LOST')).state == 'RELEASED'
            assert (await service.try_reserve_capacity(req)).state == 'RELEASED'
        finally:
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('reason', ['NOT_AUTHORIZED', 'RECOVERING', 'STALE_OBSERVATION', 'CAPACITY_PROTOCOL_UNSUPPORTED'])
def test_host_refusal_cannot_create_capacity(tmp_path, reason):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        authority = Authority()
        authority.reason = reason
        service = facade(ledger, authority=authority)
        try:
            assert (await service.try_reserve_capacity(request('new_session'))).reason == reason
            assert (await ledger.owned_slot_page()).reservations == ()
        finally:
            ledger.close()
    asyncio.run(run())


def test_authority_changes_during_reserve_and_consume_are_compensated(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        authority = Authority()
        service = facade(ledger, authority=authority)
        req = request('new_session')
        try:
            async def revoked_on_second(req, action):
                return 'NOT_AUTHORIZED' if len(authority.calls) > 1 else 'AVAILABLE'
            authority.hook = revoked_on_second
            assert (await service.try_reserve_capacity(req)).reason == 'NOT_AUTHORIZED'
            assert (await ledger.owned_slot_page()).reservations == ()
            req = replace(req, attempt_id='next', scope=replace(req.scope, session_id='next'))
            authority.hook = None
            held = await service.try_reserve_capacity(req)
            authority.calls.clear()
            authority.hook = revoked_on_second
            with pytest.raises(CoreError, match='NOT_AUTHORIZED'):
                await service.consume_capacity(req, held.reservation_id, consumed('new_session'))
            state = await ledger.get_capacity_slot(req, now=10, boot_id='boot-1')
            assert state.state == 'RELEASE_PENDING' and state.consumption is not None
            assert len((await ledger.owned_slot_page()).reservations) == 1
        finally:
            ledger.close()
    asyncio.run(run())


def test_new_owner_can_lookup_and_cancel_old_hold_but_not_consume(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        req = request('new_session')
        try:
            old = facade(ledger)
            held = await old.try_reserve_capacity(req)
            current = facade(ledger, boot='boot-2', clock=FakeClock(1))
            assert (await current.get_capacity_reservation(req)).state == 'HELD'
            with pytest.raises(CoreError, match='STALE_OBSERVATION'):
                await current.consume_capacity(req, held.reservation_id, consumed('new_session'))
            assert (await current.release_capacity(req, held.reservation_id, 'REVOKED')).state == 'RELEASED'
        finally:
            ledger.close()
    asyncio.run(run())


def test_real_r4_readiness_scope_lease_and_bound_native_dispatch(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock, owned_slot_ledger=ledger, capacity_enabled=True)
        service = facade(ledger, runtime=runtime, clock=clock, boot='capacity-owner-boot')
        lease = await attempt(runtime, clock)
        req = capacity_request(lease)
        try:
            assert (await service.assess_capacity(req)).reason == 'RECOVERING'
            installed = await runtime.install_r4_lease(lease, grant(lease))
            await open_session(runtime, installed.context)
            assert (await service.assess_capacity(req)).available
            for field in ('agent_id', 'binding_id', 'workspace_id', 'workspace_binding_id',
                          'authorization_revision', 'configuration_revision', 'session_owner_generation',
                          'connection_generation', 'credential_epoch', 'binding_revision'):
                old = getattr(req.scope, field)
                bad = replace(req, scope=replace(req.scope, **{field: old + 1 if type(old) is int else old + '-other'}))
                assert (await service.assess_capacity(bad)).reason == 'STALE_OBSERVATION'
            held = await service.try_reserve_capacity(req)
            frame = operation(lease)
            bound = prepare_r4_receipt_binding(frame, installed.context)
            assert bound['core_intent_hash'] != frame['intent_hash']
            consumed_record = CapacityConsumption(frame['operation_id'], frame['intent_hash'], None, None)
            await service.consume_capacity(req, held.reservation_id, consumed_record)
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await runtime.submit(TurnOperation('turn', 'session', 'Hello'), installed.context)
            assert (await service.bind_admitted_capacity_operation(bound)).reservation_id == held.reservation_id
            await runtime.submit(TurnOperation('turn', 'session', 'Hello'), installed.context)
            assert factory.native.sent == [('send_turn', {'text': 'Hello'}, 'turn')]
            # Fake observe says IDLE, but the real operation still owns the gate.
            other = replace(req, attempt_id='other')
            assert (await service.try_reserve_capacity(other)).reason == 'BUSY_AFFINITY'
            assert (await service.try_reserve_capacity(req)).state == 'CONSUMED'
            clock.advance(61)
            assert (await service.assess_capacity(other)).reason == 'NOT_AUTHORIZED'
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
            ledger.close()
    asyncio.run(run())


def test_binding_is_immutable_and_cannot_cross_agent_or_operation(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        req, c = request('new_session'), consumed('new_session')
        service = facade(ledger)
        try:
            held = await service.try_reserve_capacity(req)
            await service.consume_capacity(req, held.reservation_id, c)
            bound = receipt_binding(req, 'runtime.open', c.opening_operation_id, c.opening_intent_hash, 'sha256:' + 'f' * 64)
            await service.bind_capacity_operation(req, held.reservation_id, bound)
            await service.bind_capacity_operation(req, held.reservation_id, bound)
            other = receipt_binding(req, 'runtime.open', c.opening_operation_id, c.opening_intent_hash, 'sha256:' + 'e' * 64)
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await service.bind_capacity_operation(req, held.reservation_id, other)
            for change in (replace(req, scope=replace(req.scope, agent_id='other')),
                           replace(req, scope=replace(req.scope, connection_generation=2))):
                other = receipt_binding(change, 'runtime.open', c.opening_operation_id, c.opening_intent_hash, 'sha256:' + 'f' * 64)
                with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                    await service.bind_capacity_operation(req, held.reservation_id, other)
        finally:
            ledger.close()
    asyncio.run(run())


def test_readiness_timeout_does_not_occupy_next_turn(tmp_path):
    class Unresponsive:
        async def capacity_readiness(self, request):
            await asyncio.Event().wait()
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        service = ExecutionCapacity(ledger, authority=Authority(), runtime_lookup=lambda _: Unresponsive(),
            boot_id='boot-1', clock=FakeClock(10), observation_timeout_seconds=0.01)
        try:
            assert (await service.try_reserve_capacity(request())).reason == 'STALE_OBSERVATION'
            assert await ledger.get_capacity_slot(request(), now=10, boot_id='boot-1') is None
        finally:
            ledger.close()
    asyncio.run(run())


def test_uncooperative_probe_is_bounded_coalesced_and_cannot_block_another_candidate(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        authority = Authority()
        release = asyncio.Event()
        count = 0
        async def scope(req, action):
            nonlocal count
            if req.attempt_id == 'attempt-1':
                count += 1
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        pass  # Simulate an adapter that refuses cancellation.
            return 'AVAILABLE'
        authority.hook = scope
        service = ExecutionCapacity(ledger, authority=authority, runtime_lookup=lambda _: None,
            boot_id='boot-1', clock=FakeClock(10), observation_timeout_seconds=0.01)
        req = request('new_session')
        try:
            for _ in range(3):
                result = await asyncio.wait_for(service.try_reserve_capacity(req), 0.2)
                assert result.reason == 'STALE_OBSERVATION'
            assert count == 1
            other = replace(req, attempt_id='another', scope=replace(req.scope, session_id='another'))
            held = await asyncio.wait_for(service.try_reserve_capacity(other), 0.5)
            assert held.state == 'HELD'
            assert await ledger.get_capacity_slot(req, now=10, boot_id='boot-1') is None
        finally:
            release.set()
            assert await service.aclose() == 0
            ledger.close()
    asyncio.run(run())


def test_initially_unauthorized_binding_cannot_cancel_another_reservation(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        authority = Authority()
        service = facade(ledger, authority=authority)
        req, c = request('new_session'), consumed('new_session')
        try:
            held = await service.try_reserve_capacity(req)
            await service.consume_capacity(req, held.reservation_id, c)
            authority.reason = 'NOT_AUTHORIZED'
            bound = receipt_binding(req, 'runtime.open', c.opening_operation_id, c.opening_intent_hash, 'sha256:' + 'f' * 64)
            with pytest.raises(CoreError, match='NOT_AUTHORIZED'):
                await service.bind_capacity_operation(req, held.reservation_id, bound)
            assert (await ledger.get_capacity_slot(req, now=10, boot_id='boot-1')).state == 'CONSUMED'
        finally:
            ledger.close()
    asyncio.run(run())


def test_r4_cold_reservation_transfers_without_launching_during_reserve(tmp_path):
    async def run():
        from nexus_connector_core.installation import effective_installation_ref
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock, owned_slot_ledger=ledger, capacity_enabled=True)
        service = facade(ledger, runtime=runtime, clock=clock, boot='capacity-owner-boot')
        lease = await attempt(runtime, clock)
        req = capacity_request(lease, 'new_session')
        try:
            held = await service.try_reserve_capacity(req)
            assert held.state == 'HELD' and factory.open_count == 0
            installed = await runtime.install_r4_lease(lease, grant(lease))
            prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), installed.context)
            opening = operation(lease, 'reserved-open', action='runtime.open', payload=dict(
                adapter_id='codex_app_server', candidate_ref=effective_installation_ref(prepared.candidate),
                inventory_revision='sha256:' + 'b' * 64, realization_ref='realization',
                realization_revision=1, profile_revision=1, mode='managed'))
            turn = operation(lease, 'reserved-turn')
            c = CapacityConsumption(turn['operation_id'], turn['intent_hash'], opening['operation_id'], opening['intent_hash'])
            await service.consume_capacity(req, held.reservation_id, c)
            bound_open = prepare_r4_receipt_binding(opening, installed.context, prepared=prepared, stream_epoch='epoch')
            assert (await service.bind_admitted_capacity_operation(bound_open)).reservation_id == held.reservation_id
            assert factory.open_count == 0
            await runtime.open(OpenOperation('reserved-open', 'session', 'epoch', prepared), installed.context)
            assert len((await ledger.owned_slot_page()).reservations) == 1
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await runtime.submit(TurnOperation('unrelated', 'session', 'must wait'), installed.context)
            await service.bind_admitted_capacity_operation(prepare_r4_receipt_binding(turn, installed.context))
            await runtime.submit(TurnOperation('reserved-turn', 'session', 'Hello'), installed.context)
            assert factory.open_count == 1
            assert factory.native.sent == [('send_turn', {'text': 'Hello'}, 'reserved-turn')]
        finally:
            await service.aclose()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
            ledger.close()
    asyncio.run(run())


def test_released_capacity_binding_replays_only_existing_receipt_not_native_effect(tmp_path):
    from nexus_connector_core import RuntimeEvent
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock, owned_slot_ledger=ledger, capacity_enabled=True)
        service = facade(ledger, runtime=runtime, clock=clock, boot='capacity-owner-boot')
        lease = await attempt(runtime, clock)
        req = capacity_request(lease)
        try:
            installed = await runtime.install_r4_lease(lease, grant(lease))
            await open_session(runtime, installed.context)
            frame = operation(lease)
            binding = prepare_r4_receipt_binding(frame, installed.context)
            held = await service.try_reserve_capacity(req)
            await service.consume_capacity(req, held.reservation_id,
                CapacityConsumption(frame['operation_id'], frame['intent_hash'], None, None))
            await service.bind_admitted_capacity_operation(binding)
            turn = TurnOperation(frame['operation_id'], 'session', 'Hello')
            first = await runtime.submit(turn, installed.context)
            await factory.native.queue.put(RuntimeEvent(lease.scope['server_id'], lease.scope['executor_id'],
                'session', 'epoch', 0, 'turn_state', 'turn/completed',
                {'delivery_phase': 'terminal', 'turn_id': frame['operation_id']}, frame['operation_id']))
            async with asyncio.timeout(2):
                while (await service.get_capacity_reservation(req)).state != 'RELEASED':
                    await asyncio.sleep(.005)
            assert (await service.bind_admitted_capacity_operation(binding)).state == 'RELEASED'
            assert await runtime.submit(turn, installed.context) == first
            assert len(factory.native.sent) == 1
        finally:
            await service.aclose()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
            ledger.close()
    asyncio.run(run())
