"""T24: actual ledger transactions recover the same physical reservation."""
import asyncio
import json
import sqlite3

import pytest

from nexus_connector_core import CoreError, SQLiteOwnedSlotLedger
from test_capacity_contract import request, consumed
from test_capacity_slot_ledger import key, observation, receipt_binding
from test_capacity_slot_ledger import bind_consumption


CASES = [(unit, stage) for unit in ('new_session', 'next_turn')
         for stage in ('reserve', 'consume', 'bind_turn', 'release', 'expire')]
CASES.append(('new_session', 'bind_open'))


@pytest.mark.parametrize('boundary', ['rollback', 'lost_reply'])
@pytest.mark.parametrize('unit,stage', CASES)
def test_capacity_commit_cut_survives_reopen_without_replacing_ticket(tmp_path, monkeypatch, unit, stage, boundary):
    async def run():
        path = tmp_path / 'slots.db'
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        req, consumption = request(unit), consumed(unit)
        binding = None
        held = None
        if unit == 'next_turn':
            await ledger.reserve_owned_slot(key('existing-open'), req.scope.session_id)
        if stage != 'reserve':
            held = await ledger.reserve_capacity_slot(req, **observation())
        if stage in ('bind_turn', 'bind_open', 'release'):
            await ledger.consume_capacity_slot(req, held.reservation_id, consumption, **observation())
        if stage.startswith('bind'):
            opening = stage == 'bind_open'
            binding = receipt_binding(req, 'runtime.open' if opening else 'turn.submit',
                consumption.opening_operation_id if opening else consumption.turn_operation_id,
                consumption.opening_intent_hash if opening else consumption.turn_intent_hash,
                'sha256:' + 'f' * 64)

        async def action(store):
            if stage == 'reserve':
                return await store.reserve_capacity_slot(req, **observation())
            if stage == 'consume':
                return await store.consume_capacity_slot(req, held.reservation_id, consumption, **observation())
            if stage.startswith('bind'):
                return await store.bind_capacity_operation(req, held.reservation_id, binding, **observation())
            if stage == 'release':
                return await store.release_capacity_slot(req, held.reservation_id, **observation())
            return await store.get_capacity_slot(req, **observation(30))

        original = ledger._capacity_transaction
        fired = []
        async def fail_commit(work):
            def before(db):
                result = work(db)
                if boundary == 'rollback':
                    fired.append(stage)
                    raise OSError('Ledger writes rolled back before commit')
                return result
            result = await original(before)
            fired.append(stage)
            raise OSError('Ledger committed; response was lost')
        monkeypatch.setattr(ledger, '_capacity_transaction', fail_commit)
        try:
            with pytest.raises((OSError, CoreError)):
                await action(ledger)
            assert fired == [stage]
        finally:
            ledger.close()
        reopened = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            prior = await reopened.get_capacity_slot(req, **observation())
            if stage == 'reserve' and boundary == 'rollback':
                assert prior is None
            else:
                assert prior is not None and prior.request == req
                if held is not None:
                    assert prior.reservation_id == held.reservation_id
                expected = {'reserve': 'HELD', 'consume': 'CONSUMED', 'bind_turn': 'CONSUMED',
                            'bind_open': 'CONSUMED', 'release': 'RELEASED', 'expire': 'EXPIRED_UNCONSUMED'}[stage]
                if boundary == 'rollback':
                    expected = {'consume': 'HELD', 'release': 'CONSUMED', 'expire': 'HELD'}.get(stage, expected)
                assert prior.state == expected
            result = await action(reopened)
            assert await action(reopened) == result
            final = await reopened.get_capacity_slot(req, **observation())
            assert final.request == req
            if prior is not None:
                assert final.reservation_id == prior.reservation_id
            if stage in ('consume', 'bind_turn', 'bind_open', 'release'):
                assert final.consumption == consumption
            if binding is not None:
                with sqlite3.connect(path) as conn:
                    saved = conn.execute('SELECT binding_json FROM capacity_operation_bindings').fetchall()
                    assert len(saved) == 1 and json.loads(saved[0][0]) == binding
            if stage == 'reserve':
                later = await reopened.reserve_capacity_slot(req, **observation(11))
                assert later.remaining_ms == final.remaining_ms - 1000
            if stage in ('release', 'expire'):
                assert len((await reopened.owned_slot_page()).reservations) == int(unit == 'next_turn')
                if stage == 'release':
                    with pytest.raises(CoreError):
                        await reopened.acquire_turn_slot(key(consumption.turn_operation_id), req.scope.session_id,
                                                         consumption.turn_intent_hash)
                else:
                    # An unconsumed hold has no associated operation to fence.
                    # Its consumption remains forbidden, but ordinary turns on
                    # an existing session retain their own admission semantics.
                    expired = await reopened.consume_capacity_slot(req, final.reservation_id,
                        consumption, **observation(30))
                    assert expired.state == 'EXPIRED_UNCONSUMED' and expired.consumption is None
            else:
                assert len((await reopened.owned_slot_page()).reservations) == 1
            with sqlite3.connect(path) as conn:
                assert conn.execute('SELECT count(*) FROM execution_capacity_reservations').fetchone()[0] == 1
        finally:
            reopened.close()
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['rollback', 'lost_reply'])
@pytest.mark.parametrize('stage', ['opening_gate', 'turn_gate', 'turn_terminal', 'owned_release'])
def test_productive_gate_commit_cut_never_grants_duplicate_admission(tmp_path, monkeypatch, boundary, stage):
    async def run():
        path = tmp_path / 'slots.db'
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        req, consumption = request('new_session'), consumed('new_session')
        held = await ledger.reserve_capacity_slot(req, **observation())
        await ledger.consume_capacity_slot(req, held.reservation_id, consumption, **observation())
        await bind_consumption(ledger, req, held, consumption)
        if stage != 'opening_gate':
            await ledger.reserve_owned_slot(key(consumption.opening_operation_id), req.scope.session_id,
                                           intent_hash=consumption.opening_intent_hash)
        if stage in ('turn_terminal', 'owned_release'):
            assert await ledger.acquire_turn_slot(key(consumption.turn_operation_id), req.scope.session_id,
                                                  consumption.turn_intent_hash)
        async def action(store):
            if stage == 'opening_gate':
                return await store.reserve_owned_slot(key(consumption.opening_operation_id), req.scope.session_id,
                                                      intent_hash=consumption.opening_intent_hash)
            if stage == 'turn_gate':
                return await store.acquire_turn_slot(key(consumption.turn_operation_id), req.scope.session_id,
                                                     consumption.turn_intent_hash)
            if stage == 'turn_terminal':
                return await store.finish_turn_slot(key(consumption.turn_operation_id), req.scope.session_id)
            return await store.release_owned_slot(key(consumption.opening_operation_id), req.scope.session_id)
        fired = []
        original_run = ledger._run
        class CommitCut:
            def __init__(self, db):
                self.db = db
            def __getattr__(self, name):
                return getattr(self.db, name)
            def execute(self, sql, *args):
                if sql.strip().upper() == 'COMMIT' and not fired:
                    fired.append(stage)
                    if boundary == 'lost_reply':
                        self.db.execute(sql, *args)
                    raise OSError('Productive gate commit cut')
                return self.db.execute(sql, *args)
        async def cut_run(work, **kwargs):
            return await original_run(lambda db: work(CommitCut(db)), **kwargs)
        monkeypatch.setattr(ledger, '_run', cut_run)
        try:
            with pytest.raises((OSError, CoreError)):
                await action(ledger)
            assert fired == [stage]
        finally:
            ledger.close()
        reopened = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            if stage == 'opening_gate' and boundary == 'lost_reply':
                with pytest.raises(CoreError):
                    await action(reopened)  # A retained opening gate is not a new grant.
            else:
                result = await action(reopened)
                if stage != 'opening_gate':
                    assert result is (boundary == 'rollback')
                    assert await action(reopened) is False
            with sqlite3.connect(path) as conn:
                slot = conn.execute('SELECT operation_id,released FROM owned_slot_reservations').fetchone()
                assert slot == (consumption.opening_operation_id, int(stage == 'owned_release'))
                turns = conn.execute('SELECT operation_id,active FROM execution_turn_slots').fetchall()
                assert turns == ([] if stage == 'opening_gate' else
                    [(consumption.turn_operation_id, int(stage == 'turn_gate'))])
            observed = await reopened.get_capacity_slot(req, **observation())
            assert observed.reservation_id == held.reservation_id and observed.consumption == consumption
            assert observed.state == ('RELEASED' if stage in ('turn_terminal', 'owned_release') else 'CONSUMED')
        finally:
            reopened.close()
    asyncio.run(run())
