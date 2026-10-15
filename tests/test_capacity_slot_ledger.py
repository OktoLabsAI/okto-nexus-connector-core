"""Real SQLite exclusion, transfer, crash/retry and proof-based release."""
import asyncio
from dataclasses import replace
import multiprocessing

import pytest

from nexus_connector_core import (CapacityReservation, CoreError, OperationKey,
                                  SQLiteOwnedSlotLedger, SessionKey)
from test_capacity_contract import request, consumed


def key(operation):
    return OperationKey('server', 'executor', operation)


def observation(now=10, boot_id='boot-1'):
    return {'now': now, 'boot_id': boot_id}


def receipt_binding(req, action, operation_id, canonical_hash, local_hash):
    """Synthetic trusted association for adapter tests; runtime tests also use R4 preparation."""
    from hashlib import sha256
    from nexus_connector_core import R4_PREVIEW_REVISION
    from nexus_connector_core.protocol import canonical_json
    scope = req.scope
    source = {k: getattr(scope, k) for k in (
        'server_id', 'executor_id', 'agent_id', 'binding_id', 'session_id', 'connection_generation')}
    source.update(protocol_major=1, contract_revision=R4_PREVIEW_REVISION,
                  connection_id='connection', operation_id=operation_id, intent_hash=canonical_hash)
    body = dict(schema_version=1, action=action, core_intent_hash=local_hash, source=source)
    return body | {'digest': 'sha256:' + sha256(canonical_json(body)).hexdigest()}


async def bind_consumption(ledger, req, held, c):
    for action, op, digest in [('runtime.open', c.opening_operation_id, c.opening_intent_hash),
                               ('turn.submit', c.turn_operation_id, c.turn_intent_hash)]:
        if op:
            await ledger.bind_capacity_operation(req, held.reservation_id,
                receipt_binding(req, action, op, digest, digest), **observation())


def different(req, suffix):
    return replace(req, attempt_id=req.attempt_id + suffix,
        scope=replace(req.scope, session_id=req.scope.session_id + suffix),
        affinity_key='sha256:' + suffix * 64)


def test_reserve_uses_physical_budget_and_blocks_ordinary_open(tmp_path):
    async def run():
        a = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        b = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        try:
            req = request('new_session')
            assert (await a.assess_capacity_slot(req, **observation())).available
            held = await a.reserve_capacity_slot(req, **observation())
            assert held.state == 'HELD'
            assert len((await b.owned_slot_page()).reservations) == 1
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await b.reserve_owned_slot(key('ordinary'), 'other')
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await b.reserve_owned_slot(key('steal'), 'session')
            unavailable = await b.reserve_capacity_slot(different(req, 'b'), **observation())
            assert unavailable.reason == 'HOST_FULL'
            await a.release_capacity_slot(req, held.reservation_id, **observation())
            await b.reserve_owned_slot(key('ordinary'), 'other')
        finally:
            a.close()
            b.close()
    asyncio.run(run())


def test_lost_response_retries_original_attempt_without_extending_ttl(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req = request('new_session')
        try:
            first = await ledger.reserve_capacity_slot(req, **observation())
            retry = await ledger.reserve_capacity_slot(req, **observation(11))
            assert retry.reservation_id == first.reservation_id
            assert retry.remaining_ms == first.remaining_ms - 1000
            with pytest.raises(CoreError, match='RESERVATION_CONFLICT'):
                await ledger.reserve_capacity_slot(replace(req, ttl_ms=20_000), **observation())
        finally:
            ledger.close()
        reopened = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        try:
            result = await reopened.get_capacity_slot(req, **observation(5000, 'new-boot'))
            assert result.state == 'HELD' and result.remaining_ms == 0
            assert result.reservation_id == first.reservation_id
            assert len((await reopened.owned_slot_page()).reservations) == 1
            with pytest.raises(CoreError, match='STALE_OBSERVATION'):
                await reopened.consume_capacity_slot(req, first.reservation_id, consumed('new_session'),
                                                     **observation(5000, 'new-boot'))
            # Explicit cancellation can release a durably proven unconsumed hold.
            assert (await reopened.release_capacity_slot(req, first.reservation_id,
                    **observation(5000, 'new-boot'))).state == 'RELEASED'
        finally:
            reopened.close()
    asyncio.run(run())


def test_consumption_transfer_holds_first_turn_and_uncertainty_never_expires(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req, c = request('new_session'), consumed('new_session')
        try:
            held = await ledger.reserve_capacity_slot(req, **observation())
            await ledger.consume_capacity_slot(req, held.reservation_id, c, **observation())
            await bind_consumption(ledger, req, held, c)
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await ledger.reserve_owned_slot(key(c.opening_operation_id), 'session', intent_hash=c.turn_intent_hash)
            await ledger.reserve_owned_slot(key(c.opening_operation_id), 'session', intent_hash=c.opening_intent_hash)
            assert len((await ledger.owned_slot_page()).reservations) == 1
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await ledger.reserve_owned_slot(key(c.opening_operation_id), 'session', intent_hash=c.opening_intent_hash)
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await ledger.acquire_turn_slot(key('ordinary'), 'session', c.turn_intent_hash)
            assert await ledger.acquire_turn_slot(key(c.turn_operation_id), 'session', c.turn_intent_hash)
            # Transport returning isn't terminal evidence. The hold persists.
            expired = await ledger.get_capacity_slot(req, **observation(9999))
            assert expired.state == 'CONSUMED'
            pending = await ledger.release_capacity_slot(req, held.reservation_id, **observation(9999))
            assert pending.state == 'RELEASE_PENDING'
            assert len((await ledger.owned_slot_page()).reservations) == 1
            assert not await ledger.finish_turn_slot(key('unrelated'), 'session')
            assert await ledger.finish_turn_slot(key(c.turn_operation_id), 'session')
            assert (await ledger.get_capacity_slot(req, **observation(9999))).state == 'RELEASED'
            # Finishing a turn does not pretend the still-live process stopped.
            assert len((await ledger.owned_slot_page()).reservations) == 1
            assert await ledger.acquire_turn_slot(key('next'), 'session', c.turn_intent_hash)
            assert not await ledger.finish_turn_slot(key(c.turn_operation_id), 'session')
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await ledger.acquire_turn_slot(key('third'), 'session', c.turn_intent_hash)
            assert await ledger.release_owned_slot(key(c.opening_operation_id), 'session')
            assert (await ledger.owned_slot_page()).reservations == ()
        finally:
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('ordinary_first', [False, True])
def test_next_turn_reservation_and_ordinary_admission_share_gate(tmp_path, ordinary_first):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
        req, c = request(), consumed()
        try:
            await ledger.reserve_owned_slot(key('open'), 'session')
            if ordinary_first:
                assert await ledger.acquire_turn_slot(key('ordinary'), 'session', c.turn_intent_hash)
                assert (await ledger.reserve_capacity_slot(req, **observation())).reason == 'BUSY_AFFINITY'
                assert await ledger.get_capacity_slot(req, **observation()) is None
                await ledger.finish_turn_slot(key('ordinary'), 'session')
            held = await ledger.reserve_capacity_slot(req, **observation())
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await ledger.acquire_turn_slot(key('new-ordinary'), 'session', c.turn_intent_hash)
            await ledger.consume_capacity_slot(req, held.reservation_id, c, **observation())
            await bind_consumption(ledger, req, held, c)
            assert await ledger.acquire_turn_slot(key(c.turn_operation_id), 'session', c.turn_intent_hash)
            assert not await ledger.acquire_turn_slot(key(c.turn_operation_id), 'session', c.turn_intent_hash)
            await ledger.finish_turn_slot(key(c.turn_operation_id), 'session')
            assert not await ledger.acquire_turn_slot(key(c.turn_operation_id), 'session', c.turn_intent_hash)
            assert len((await ledger.owned_slot_page()).reservations) == 1
        finally:
            ledger.close()
    asyncio.run(run())


def test_expiration_commits_before_any_late_consume(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req = request('new_session')
        try:
            held = await ledger.reserve_capacity_slot(req, **observation())
            refused = await ledger.consume_capacity_slot(req, held.reservation_id, consumed('new_session'), **observation(20))
            assert refused.state == 'EXPIRED_UNCONSUMED' and refused.consumption is None
            assert (await ledger.owned_slot_page()).reservations == ()
            await ledger.reserve_owned_slot(key('ordinary'), 'other')
            assert (await ledger.reserve_capacity_slot(req, **observation(21))).state == 'EXPIRED_UNCONSUMED'
        finally:
            ledger.close()
    asyncio.run(run())


def test_different_session_cannot_bypass_same_affinity(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=2)
        req = request('new_session')
        try:
            await ledger.reserve_capacity_slot(req, **observation())
            bypass = replace(req, attempt_id='another', scope=replace(req.scope, session_id='fake-session'))
            assert (await ledger.reserve_capacity_slot(bypass, **observation())).reason == 'BUSY_AFFINITY'
            assert isinstance(await ledger.reserve_capacity_slot(different(req, 'b'), **observation()), CapacityReservation)
        finally:
            ledger.close()
    asyncio.run(run())


def _process_reserve(path, suffix, start, output, ordinary=False):
    async def run():
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            start.wait(20)
            if ordinary:
                try:
                    await ledger.reserve_owned_slot(key('ordinary'), 'ordinary-session')
                    output.put('HELD')
                except CoreError as error:
                    if error.code != 'CAPACITY_EXCEEDED':
                        raise
                    output.put('HOST_FULL')
            else:
                result = await ledger.reserve_capacity_slot(different(request('new_session'), suffix), **observation())
                output.put(result.state if isinstance(result, CapacityReservation) else result.reason)
        finally:
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('ordinary', [False, True])
def test_distinct_processes_race_for_last_physical_slot(tmp_path, ordinary):
    ctx = multiprocessing.get_context('spawn')
    start, output = ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=_process_reserve, args=(tmp_path / 'shared.db', s, start, output, ordinary and s == 'b'))
                 for s in ('a', 'b')]
    try:
        for process in processes:
            process.start()
        start.set()
        outcomes = [output.get(timeout=30) for _ in processes]
        assert sorted(outcomes) == ['HELD', 'HOST_FULL']
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
        output.close()


def test_bounded_expiry_does_not_expire_consumed_or_old_boot(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=5)
        try:
            reqs = [different(request('new_session'), s) for s in ('a', 'b', 'c', 'd')]
            reqs[-1] = replace(reqs[-1], scope=replace(reqs[-1].scope, boot_id='old-boot'))
            held = [await ledger.reserve_capacity_slot(req, now=10, boot_id=req.scope.boot_id) for req in reqs]
            await ledger.consume_capacity_slot(reqs[2], held[2].reservation_id, consumed('new_session'), **observation())
            assert await ledger.expire_capacity_slots(now=100, boot_id='boot-1', limit=1) == 1
            assert len((await ledger.owned_slot_page()).reservations) == 3
            assert await ledger.expire_capacity_slots(now=100, boot_id='boot-1', limit=1) == 1
            assert await ledger.expire_capacity_slots(now=100, boot_id='boot-1', limit=1) == 0
            assert len((await ledger.owned_slot_page()).reservations) == 2
        finally:
            ledger.close()
    asyncio.run(run())


def test_physical_slot_and_attempt_commit_or_rollback_together(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req = request('new_session')
        try:
            # Disk/storage failure at the second write must roll back the first.
            import sqlite3
            ledger._run_sync(lambda db: db.executescript("""
                CREATE TRIGGER failed_physical_write BEFORE INSERT ON owned_slot_reservations
                BEGIN SELECT RAISE(ABORT, 'injected write failure'); END;
            """))
            with pytest.raises(sqlite3.IntegrityError, match='injected write failure'):
                await ledger.reserve_capacity_slot(req, **observation())
            assert await ledger.get_capacity_slot(req, **observation()) is None
            assert (await ledger.owned_slot_page()).reservations == ()
            ledger._run_sync(lambda db: db.execute('DROP TRIGGER failed_physical_write'))
            assert (await ledger.reserve_capacity_slot(req, **observation())).state == 'HELD'
        finally:
            ledger.close()
    asyncio.run(run())


def test_consumed_reservation_survives_restart_until_proven_stop(tmp_path):
    async def run():
        path = tmp_path / 'slots.db'
        req, c = request('new_session'), consumed('new_session')
        first = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            held = await first.reserve_capacity_slot(req, **observation())
            await first.consume_capacity_slot(req, held.reservation_id, c, **observation())
            await bind_consumption(first, req, held, c)
            await first.reserve_owned_slot(key(c.opening_operation_id), 'session', intent_hash=c.opening_intent_hash)
            await first.acquire_turn_slot(key(c.turn_operation_id), 'session', c.turn_intent_hash)
        finally:
            first.close()
        reopened = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            assert await reopened.expire_capacity_slots(now=1000, boot_id='boot-2') == 0
            state = await reopened.get_capacity_slot(req, **observation(1000, 'boot-2'))
            assert state.state == 'CONSUMED'
            with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
                await reopened.reserve_owned_slot(key('another'), 'another')
            await reopened.release_capacity_slot(req, held.reservation_id, **observation(1000, 'boot-2'))
            assert len((await reopened.owned_slot_page()).reservations) == 1
            await reopened.release_owned_slot(key(c.opening_operation_id), 'session')
            assert (await reopened.get_capacity_slot(req, **observation(1000, 'boot-2'))).state == 'RELEASED'
            await reopened.reserve_owned_slot(key('another'), 'another')
        finally:
            reopened.close()
    asyncio.run(run())
