import asyncio
import sqlite3
from dataclasses import replace

import pytest
from nexus_connector_core import CoreError, CapacityConsumption, OperationKey, OwnedSlotState, SQLiteOwnedSlotLedger
from test_capacity_contract import request, consumed
from test_capacity_runtime import facade, Authority
from test_capacity_slot_ledger import receipt_binding, different


@pytest.mark.parametrize('legacy_identity', [False, True])
def test_consumed_slot_attribution_is_exact_read_only_and_survives_reopen(tmp_path, legacy_identity):
    async def run():
        path = tmp_path / 'slots.db'
        ledger = SQLiteOwnedSlotLedger(path)
        req, c = request('new_session'), consumed('new_session')
        try:
            held = await ledger.reserve_capacity_slot(req, now=1, boot_id='boot-1')
            if legacy_identity:
                # Older versions allocated opaque IDs; their exact stored
                # association remains authoritative after an upgrade.
                with sqlite3.connect(path) as db:
                    db.execute('UPDATE execution_capacity_reservations SET reservation_id=?', ('cap_legacy_identity',))
                    db.execute('UPDATE owned_slot_reservations SET operation_id=?', ('capacity:cap_legacy_identity',))
                held = await ledger.get_capacity_slot(req, now=1, boot_id='boot-1')
            slot, = (await ledger.owned_slot_page()).reservations
            assert await ledger.capacity_opening_for_slot(slot) is None
            await ledger.consume_capacity_slot(req, held.reservation_id, c, now=1, boot_id='boot-1')
            ledger.close()
            ledger = SQLiteOwnedSlotLedger(path)
            revision = await ledger.capacity_revision()
            assert await ledger.capacity_opening_for_slot(slot) == c.opening_operation_id
            assert await ledger.capacity_opening_for_slot(OwnedSlotState(slot.key, slot.opening_operation_id, True)) is None
            for field in ('server_id', 'executor_id', 'session_id'):
                wrong = replace(slot, key=replace(slot.key, **{field: 'other'}))
                assert await ledger.capacity_opening_for_slot(wrong) is None
            assert await ledger.capacity_opening_for_slot(replace(slot, opening_operation_id='other')) is None
            assert await ledger.capacity_revision() == revision
            assert (await ledger.owned_slot_page()).reservations == (slot,)
            # Association did not free capacity; the normal Core release must
            # still establish that this consumed opening never started.
            released = await ledger.release_capacity_slot(req, held.reservation_id, now=5, boot_id='boot-2')
            assert released.state == 'RELEASED'
            assert await ledger.capacity_opening_for_slot(slot) is None
            released_slot = await ledger.owned_slot_state(slot.key)
            assert released_slot.released
            released_revision = await ledger.capacity_revision()
            assert await ledger.capacity_opening_for_slot(released_slot) == c.opening_operation_id
            assert await ledger.capacity_revision() == released_revision
            ledger.close()
            ledger = SQLiteOwnedSlotLedger(path)
            assert await ledger.capacity_opening_for_slot(released_slot) == c.opening_operation_id
            assert not (await ledger.owned_slot_page()).reservations
        finally:
            ledger.close()
    asyncio.run(run())


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
            assert record.state == 'RELEASED'
            # Existing association is historical metadata, not another grant.
            assert (await service.bind_admitted_capacity_operation(bound)).state == 'RELEASED'
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
