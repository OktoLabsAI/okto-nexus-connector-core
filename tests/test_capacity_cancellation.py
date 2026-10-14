"""A durable negative acknowledgement fences a reserve that has not arrived."""
import asyncio
from dataclasses import replace
import multiprocessing
import sqlite3

import pytest

from nexus_connector_core import (CoreError, SQLiteOwnedSlotLedger, capacity_reservation_id,
                                  execute_capacity_control)
from test_capacity_contract import request, consumed
from test_capacity_slot_ledger import key, observation
from test_capacity_runtime import facade, Authority
from test_capacity_codec import frame


@pytest.mark.parametrize('unit', ['next_turn', 'new_session'])
def test_absent_cancellation_does_not_touch_existing_physical_work(tmp_path, unit):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req = request(unit)
        try:
            await ledger.reserve_owned_slot(key('ordinary-open'), req.scope.session_id)
            if unit == 'next_turn':
                await ledger.acquire_turn_slot(key('ordinary-turn'), req.scope.session_id, 'sha256:' + 'a' * 64)
            before = (await ledger.owned_slot_page()).reservations
            cancelled = await ledger.release_capacity_slot(req, capacity_reservation_id(req), **observation())
            assert cancelled.state == 'RELEASED' and cancelled.consumption is None
            assert cancelled.remaining_ms == 0
            assert (await ledger.owned_slot_page()).reservations == before
            late = await ledger.reserve_capacity_slot(req, **observation())
            assert late == cancelled
            assert (await ledger.release_capacity_slot(req, cancelled.reservation_id, **observation())) == cancelled
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.consume_capacity_slot(req, cancelled.reservation_id, consumed(unit), **observation())
            if unit == 'next_turn':
                # Cancellation of a nonexistent ticket did not finish this turn.
                with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                    await ledger.acquire_turn_slot(key('other-turn'), req.scope.session_id, 'sha256:' + 'b' * 64)
        finally:
            ledger.close()
    asyncio.run(run())


def test_cancellation_identity_and_original_scope_are_immutable(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req = request('new_session')
        try:
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.release_capacity_slot(req, 'unknown-reservation', **observation())
            assert await ledger.get_capacity_slot(req, **observation()) is None
            terminal = await ledger.release_capacity_slot(req, capacity_reservation_id(req), **observation())
            changed = replace(req, ttl_ms=req.ttl_ms + 100)
            for invoke in (lambda: ledger.reserve_capacity_slot(changed, **observation()),
                           lambda: ledger.release_capacity_slot(changed, capacity_reservation_id(changed), **observation())):
                with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                    await invoke()
            assert (await ledger.get_capacity_slot(req, **observation())) == terminal
            assert not (await ledger.owned_slot_page()).reservations
        finally:
            ledger.close()
    asyncio.run(run())


def test_existing_opaque_reservation_ids_remain_authoritative_after_upgrade(tmp_path):
    path = tmp_path / 'slots.db'
    req = request('new_session')

    async def seed():
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            return await ledger.reserve_capacity_slot(req, **observation())
        finally:
            ledger.close()

    held = asyncio.run(seed())
    # Reproduce the random opaque ID written by an earlier Core version.
    with sqlite3.connect(path) as db:
        db.execute('UPDATE execution_capacity_reservations SET reservation_id=? WHERE reservation_id=?',
                   ('cap_legacy_random_identity', held.reservation_id))
        db.execute('UPDATE owned_slot_reservations SET operation_id=? WHERE operation_id=?',
                   ('capacity:cap_legacy_random_identity', 'capacity:' + held.reservation_id))

    async def recover():
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            current = await ledger.reserve_capacity_slot(req, **observation())
            assert current.reservation_id == 'cap_legacy_random_identity'
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.release_capacity_slot(req, capacity_reservation_id(req), **observation())
            assert len((await ledger.owned_slot_page()).reservations) == 1
            released = await ledger.release_capacity_slot(req, current.reservation_id, **observation())
            assert released.state == 'RELEASED' and released.reservation_id == current.reservation_id
            assert not (await ledger.owned_slot_page()).reservations
        finally:
            ledger.close()
    asyncio.run(recover())


def test_racing_release_cannot_erase_consumption_or_free_a_possible_effect(tmp_path):
    async def run():
        path = tmp_path / 'slots.db'
        first, second = SQLiteOwnedSlotLedger(path, max_slots=1), SQLiteOwnedSlotLedger(path, max_slots=1)
        req = request('new_session')
        try:
            held = await first.reserve_capacity_slot(req, **observation())
            assert held.reservation_id == capacity_reservation_id(req)
            results = await asyncio.gather(
                first.consume_capacity_slot(req, held.reservation_id, consumed('new_session'), **observation()),
                second.release_capacity_slot(req, capacity_reservation_id(req), **observation()), return_exceptions=True)
            state = await second.get_capacity_slot(req, **observation())
            if state.consumption is None:
                assert state.state == 'RELEASED'
                assert isinstance(results[0], CoreError) and results[0].code == 'RESERVATION_CONFLICT'
                assert not (await first.owned_slot_page()).reservations
            else:
                assert state.state == 'RELEASE_PENDING'
                assert len((await first.owned_slot_page()).reservations) == 1
        finally:
            first.close()
            second.close()
    asyncio.run(run())


def test_control_cancellation_requires_authority_and_survives_revoked_reserve_authority(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        authority = Authority()
        service = facade(ledger, authority=authority)
        req = request('new_session')
        call = frame() | dict(type='capacity.release', request=req.to_dict(),
            reservation_id=capacity_reservation_id(req), reason='CANCELLED')
        try:
            authority.reason = 'NOT_AUTHORIZED'
            refusal = await execute_capacity_control(service, call)
            assert refusal['result']['reason'] == 'NOT_AUTHORIZED'
            assert await ledger.get_capacity_slot(req, **observation()) is None
            async def recovery_only(req, action):
                return 'AVAILABLE' if action in ('get', 'release') else 'NOT_AUTHORIZED'
            authority.hook = recovery_only
            cancelled = await execute_capacity_control(service, call)
            assert cancelled['result']['state'] == 'RELEASED'
            assert (await service.get_capacity_reservation(req)).consumption is None
            authority.hook = None
            authority.reason = 'AVAILABLE'
            assert (await service.try_reserve_capacity(req)).state == 'RELEASED'
            assert not (await ledger.owned_slot_page()).reservations
        finally:
            await service.aclose()
            ledger.close()
    asyncio.run(run())


def _delayed_reserver(path, ready, deliver, output):
    async def run():
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        req = request('new_session')
        try:
            assert await ledger.get_capacity_slot(req, **observation()) is None
            ready.set()
            assert deliver.wait(20)
            late = await ledger.reserve_capacity_slot(req, **observation())
            output.put((late.state, len((await ledger.owned_slot_page()).reservations)))
        finally:
            ledger.close()
    asyncio.run(run())


def test_other_process_delayed_reserve_cannot_recreate_cancelled_capacity(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    ready, deliver, output = ctx.Event(), ctx.Event(), ctx.Queue()
    path = tmp_path / 'shared.db'
    child = ctx.Process(target=_delayed_reserver, args=(path, ready, deliver, output))
    child.start()
    try:
        assert ready.wait(15)
        async def cancel():
            ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
            req = request('new_session')
            try:
                await ledger.release_capacity_slot(req, capacity_reservation_id(req), **observation())
            finally:
                ledger.close()
        asyncio.run(cancel())
        deliver.set()
        assert output.get(timeout=20) == ('RELEASED', 0)
        child.join(timeout=10)
        assert child.exitcode == 0
        async def after_restart():
            ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
            try:
                found = await ledger.get_capacity_slot(request('new_session'), **observation(9999, 'new-boot'))
                assert found.state == 'RELEASED' and found.consumption is None
                assert not (await ledger.owned_slot_page()).reservations
            finally:
                ledger.close()
        asyncio.run(after_restart())
    finally:
        deliver.set()
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
        output.close()
