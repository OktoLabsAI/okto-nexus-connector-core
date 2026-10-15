"""Consumption is retained, but unused capacity can be fenced atomically."""
import asyncio

import pytest

from nexus_connector_core import CoreError, SQLiteOwnedSlotLedger
from test_capacity_contract import request, consumed
from test_capacity_slot_ledger import key, observation, bind_consumption


@pytest.mark.parametrize('unit', ['new_session', 'next_turn'])
@pytest.mark.parametrize('bound', [False, True])
def test_consumed_but_unstarted_reservation_releases_without_late_execution(tmp_path, unit, bound):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req, c = request(unit), consumed(unit)
        try:
            if unit == 'next_turn':
                await ledger.reserve_owned_slot(key('ordinary-open'), req.scope.session_id)
            held = await ledger.reserve_capacity_slot(req, **observation())
            await ledger.consume_capacity_slot(req, held.reservation_id, c, **observation())
            if bound:
                await bind_consumption(ledger, req, held, c)
            released = await ledger.release_capacity_slot(req, held.reservation_id, **observation())
            assert released.state == 'RELEASED' and released.consumption == c
            assert await ledger.release_capacity_slot(req, held.reservation_id, **observation()) == released
            assert await ledger.get_capacity_slot(req, **observation(9999, 'new-boot')) == released
            assert len((await ledger.owned_slot_page()).reservations) == int(unit == 'next_turn')
            if unit == 'new_session':
                with pytest.raises(CoreError):
                    await ledger.reserve_owned_slot(key(c.opening_operation_id), req.scope.session_id, intent_hash=c.opening_intent_hash)
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.acquire_turn_slot(key(c.turn_operation_id), req.scope.session_id, c.turn_intent_hash)
            if not bound:
                with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                    await bind_consumption(ledger, req, held, c)
        finally:
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('unit', ['new_session', 'next_turn'])
def test_started_resource_requires_correlated_stop_or_terminal_proof(tmp_path, unit):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req, c = request(unit), consumed(unit)
        try:
            if unit == 'next_turn':
                await ledger.reserve_owned_slot(key('ordinary-open'), req.scope.session_id)
            held = await ledger.reserve_capacity_slot(req, **observation())
            await ledger.consume_capacity_slot(req, held.reservation_id, c, **observation())
            await bind_consumption(ledger, req, held, c)
            if unit == 'new_session':
                await ledger.reserve_owned_slot(key(c.opening_operation_id), req.scope.session_id, intent_hash=c.opening_intent_hash)
            else:
                assert await ledger.acquire_turn_slot(key(c.turn_operation_id), req.scope.session_id, c.turn_intent_hash)
            pending = await ledger.release_capacity_slot(req, held.reservation_id, **observation())
            assert pending.state == 'RELEASE_PENDING' and pending.consumption == c
            assert len((await ledger.owned_slot_page()).reservations) == 1
            assert await ledger.release_capacity_slot(req, held.reservation_id, **observation(99999, 'new-boot')) == pending
        finally:
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('unit', ['new_session', 'next_turn'])
def test_native_admission_and_cancellation_serialize_across_independent_ledgers(tmp_path, unit):
    async def run():
        path = tmp_path / 'slots.db'
        a, b = SQLiteOwnedSlotLedger(path, max_slots=1), SQLiteOwnedSlotLedger(path, max_slots=1)
        req, c = request(unit), consumed(unit)
        try:
            if unit == 'next_turn':
                await a.reserve_owned_slot(key('ordinary-open'), req.scope.session_id)
            held = await a.reserve_capacity_slot(req, **observation())
            await a.consume_capacity_slot(req, held.reservation_id, c, **observation())
            await bind_consumption(a, req, held, c)
            start = (a.acquire_turn_slot(key(c.turn_operation_id), req.scope.session_id, c.turn_intent_hash)
                if unit == 'next_turn' else a.reserve_owned_slot(key(c.opening_operation_id), req.scope.session_id,
                                                               intent_hash=c.opening_intent_hash))
            results = await asyncio.gather(start,
                b.release_capacity_slot(req, held.reservation_id, **observation()), return_exceptions=True)
            observed = await a.get_capacity_slot(req, **observation())
            if observed.state == 'RELEASED':
                assert isinstance(results[0], CoreError)
            else:
                assert observed.state == 'RELEASE_PENDING' and not isinstance(results[0], Exception)
            assert observed.consumption == c
            assert len((await a.owned_slot_page()).reservations) == int(unit == 'next_turn' or observed.state == 'RELEASE_PENDING')
        finally:
            a.close()
            b.close()
    asyncio.run(run())
