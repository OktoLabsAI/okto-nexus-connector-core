import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import SQLiteOwnedSlotLedger, CapacityConsumption, CoreError
from test_capacity_contract import request


def req(name, generation=1, executor='executor'):
    original = request('new_session')
    return replace(original, attempt_id=name, affinity_key='sha256:' + name[0] * 64,
        scope=replace(original.scope, session_id=name, connection_generation=generation, executor_id=executor))


def test_replacement_releases_only_proven_unconsumed_old_generation_without_clock_expiry(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=8)
        old, consumed, current, foreign = req('a'), req('b'), req('c', 2), req('d', executor='foreign')
        try:
            states = [await ledger.reserve_capacity_slot(r, now=10, boot_id=r.scope.boot_id)
                      for r in (old, consumed, current, foreign)]
            await ledger.consume_capacity_slot(consumed, states[1].reservation_id,
                CapacityConsumption('turn', 'sha256:' + '1' * 64, 'open', 'sha256:' + '2' * 64),
                now=10, boot_id=consumed.scope.boot_id)
            assert await ledger.release_fenced_capacity_holds('server', 'executor', connection_generation=2) == 1
            assert await ledger.release_fenced_capacity_holds('server', 'executor', connection_generation=2) == 0
            facts = [await ledger.get_capacity_slot(r, now=99999, boot_id='new-clock')
                     for r in (old, consumed, current, foreign)]
            assert [r.state for r in facts] == ['RELEASED', 'CONSUMED', 'HELD', 'HELD']
            assert len((await ledger.owned_slot_page()).reservations) == 3
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.consume_capacity_slot(old, states[0].reservation_id,
                    CapacityConsumption('late', 'sha256:' + '3' * 64, 'late-open', 'sha256:' + '4' * 64),
                    now=11, boot_id=old.scope.boot_id)
        finally:
            ledger.close()
    asyncio.run(run())


def test_active_capacity_pages_have_stable_scope_and_high_water_under_new_insertions(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=10)
        try:
            for name in ('a', 'b', 'c'):
                r = req(name)
                await ledger.reserve_capacity_slot(r, now=10, boot_id=r.scope.boot_id)
            first = await ledger.capacity_reservation_page('server', 'executor', limit=1)
            assert [r.request.attempt_id for r in first.reservations] == ['a']
            assert first.reservations[0].remaining_ms == 0 and first.reservations[0].state == 'HELD'
            for r in (req('d'), req('e', executor='foreign')):
                await ledger.reserve_capacity_slot(r, now=10, boot_id=r.scope.boot_id)
            after, found = first.next_after_rowid, ['a']
            while after is not None:
                page = await ledger.capacity_reservation_page('server', 'executor', limit=1,
                    after_rowid=after, high_water_rowid=first.high_water_rowid)
                found.extend(r.request.attempt_id for r in page.reservations)
                after = page.next_after_rowid
            assert found == ['a', 'b', 'c']
            assert await ledger.release_fenced_capacity_holds('server', 'executor', connection_generation=2, limit=2) == 2
            assert await ledger.release_fenced_capacity_holds('server', 'executor', connection_generation=2, limit=2) == 2
            assert not (await ledger.capacity_reservation_page('server', 'executor')).reservations
            assert len((await ledger.capacity_reservation_page('server', 'foreign')).reservations) == 1
        finally:
            ledger.close()
    asyncio.run(run())


def test_consume_and_fenced_hold_release_cannot_both_win(tmp_path):
    async def run():
        path = tmp_path / 'slots.db'
        first, second = SQLiteOwnedSlotLedger(path, max_slots=1), SQLiteOwnedSlotLedger(path, max_slots=1)
        r = req('a')
        try:
            held = await first.reserve_capacity_slot(r, now=10, boot_id=r.scope.boot_id)
            result = await asyncio.gather(
                first.consume_capacity_slot(r, held.reservation_id,
                    CapacityConsumption('turn', 'sha256:' + '1' * 64, 'open', 'sha256:' + '2' * 64),
                    now=11, boot_id=r.scope.boot_id),
                second.release_fenced_capacity_holds('server', 'executor', connection_generation=2),
                return_exceptions=True)
            found = await first.get_capacity_slot(r, now=1000, boot_id='new-boot')
            slots = (await first.owned_slot_page()).reservations
            if found.state == 'CONSUMED':
                assert result[1] == 0 and len(slots) == 1
            else:
                assert found.state == 'RELEASED' and result[1] == 1 and not slots
                assert isinstance(result[0], CoreError)
        finally:
            first.close()
            second.close()
    asyncio.run(run())


def test_retiring_unused_next_turn_does_not_release_its_live_process(tmp_path):
    from nexus_connector_core import OperationKey
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        r = replace(req('a'), unit='next_turn')
        try:
            await ledger.reserve_owned_slot(OperationKey('server', 'executor', 'ordinary-open'), r.scope.session_id)
            held = await ledger.reserve_capacity_slot(r, now=10, boot_id=r.scope.boot_id)
            assert held.state == 'HELD'
            assert await ledger.release_fenced_capacity_holds('server', 'executor', connection_generation=2) == 1
            assert (await ledger.get_capacity_slot(r, now=99999, boot_id='new')).state == 'RELEASED'
            slots = (await ledger.owned_slot_page()).reservations
            assert len(slots) == 1 and slots[0].opening_operation_id == 'ordinary-open'
        finally:
            ledger.close()
    asyncio.run(run())
