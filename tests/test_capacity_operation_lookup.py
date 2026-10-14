import asyncio
from dataclasses import replace

import pytest
from nexus_connector_core import CoreError, CapacityConsumption, OperationKey, SQLiteOwnedSlotLedger
from test_capacity_contract import request, consumed
from test_capacity_runtime import facade, Authority
from test_capacity_slot_ledger import receipt_binding, different


@pytest.mark.parametrize('overlap', ['same_turn', 'same_open', 'cross_action'])
def test_canonical_operation_cannot_be_consumed_by_two_reservations(tmp_path, overlap):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=2)
        req, c = request('new_session'), consumed('new_session')
        other = different(req, 'b')
        try:
            a = await ledger.reserve_capacity_slot(req, now=1, boot_id='boot-1')
            b = await ledger.reserve_capacity_slot(other, now=1, boot_id='boot-1')
            second = CapacityConsumption(
                c.turn_operation_id if overlap == 'same_turn' else c.opening_operation_id if overlap == 'cross_action' else 'other-turn',
                c.turn_intent_hash,
                c.opening_operation_id if overlap == 'same_open' else 'other-open', c.opening_intent_hash)
            results = await asyncio.gather(
                ledger.consume_capacity_slot(req, a.reservation_id, c, now=1, boot_id='boot-1'),
                ledger.consume_capacity_slot(other, b.reservation_id, second, now=1, boot_id='boot-1'),
                return_exceptions=True)
            assert sum(isinstance(x, CoreError) and x.code == 'RESERVATION_CONFLICT' for x in results) == 1
            assert sum(getattr(x, 'state', None) == 'CONSUMED' for x in results) == 1
        finally:
            ledger.close()
    asyncio.run(run())


def test_operation_lookup_is_exact_historical_and_requires_current_authority_before_binding(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        req, c, authority = request('new_session'), consumed('new_session'), Authority()
        service = facade(ledger, authority=authority)
        try:
            ordinary = receipt_binding(req, 'turn.submit', 'normal', c.turn_intent_hash, 'sha256:' + 'f' * 64)
            assert await service.bind_admitted_capacity_operation(ordinary) is None
            held = await service.try_reserve_capacity(req)
            await service.consume_capacity(req, held.reservation_id, c)
            bound = receipt_binding(req, 'runtime.open', c.opening_operation_id, c.opening_intent_hash, 'sha256:' + 'f' * 64)
            key = OperationKey(req.scope.server_id, req.scope.executor_id, c.opening_operation_id)
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.capacity_for_operation(key, action='turn.submit', now=10, boot_id='boot-1')
            authority.reason = 'NOT_AUTHORIZED'
            with pytest.raises(CoreError, match='NOT_AUTHORIZED'):
                await service.bind_admitted_capacity_operation(bound)
            authority.reason = 'AVAILABLE'
            assert (await service.bind_admitted_capacity_operation(bound)).reservation_id == held.reservation_id
            wrong = receipt_binding(req, 'runtime.open', c.opening_operation_id, 'sha256:' + '0' * 64, 'sha256:' + 'f' * 64)
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await service.bind_admitted_capacity_operation(wrong)
            await service.release_capacity(req, held.reservation_id, 'CANCELLED')
            record = await ledger.capacity_for_operation(key, action='runtime.open', now=9999, boot_id='next-boot')
            assert record.state == 'RELEASE_PENDING'
            # Existing association is historical metadata, not another grant.
            assert (await service.bind_admitted_capacity_operation(bound)).state == 'RELEASE_PENDING'
            late = receipt_binding(req, 'turn.submit', c.turn_operation_id, c.turn_intent_hash, 'sha256:' + 'e' * 64)
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await service.bind_admitted_capacity_operation(late)
        finally:
            await service.aclose()
            ledger.close()
    asyncio.run(run())


def test_reserved_operation_cannot_reenter_as_ordinary_work_in_another_session(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        req = request('next_turn')
        c = consumed('next_turn')
        try:
            await ledger.reserve_owned_slot(OperationKey('server', 'executor', 'open'), req.scope.session_id)
            await ledger.reserve_owned_slot(OperationKey('server', 'executor', 'other-open'), 'other-session')
            held = await ledger.reserve_capacity_slot(req, now=10, boot_id='boot-1')
            await ledger.consume_capacity_slot(req, held.reservation_id, c, now=10, boot_id='boot-1')
            key = OperationKey('server', 'executor', c.turn_operation_id)
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.acquire_turn_slot(key, 'other-session', c.turn_intent_hash)
            await ledger.release_capacity_slot(req, held.reservation_id, now=10, boot_id='boot-1')
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.acquire_turn_slot(key, req.scope.session_id, c.turn_intent_hash)
        finally:
            ledger.close()
    asyncio.run(run())
