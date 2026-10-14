"""SQLite capacity operations sharing the installation's physical slot ledger.

Only the trusted Core calls this adapter. It is not an authorization service.
All mutations are short transactions on the existing ledger worker. Provider
I/O and remote clocks never participate in a transaction. Consumed resources
have no expiry: only correlated terminal evidence or containment releases them.
"""
from __future__ import annotations

import json
import math
import uuid

from .capacity import (CAPACITY_CONTRACT_REVISION, CapacityAssessment,
                       CapacityConsumption, CapacityRequest, CapacityReservation, CapacityReservationPage)
from .models import CoreError


SCHEMA = """
CREATE TABLE IF NOT EXISTS capacity_revision (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL
);
INSERT OR IGNORE INTO capacity_revision VALUES(1,0);
CREATE TABLE IF NOT EXISTS execution_capacity_reservations (
    reservation_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL, executor_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    session_id TEXT NOT NULL, affinity_key TEXT NOT NULL,
    request_json TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
    deadline REAL NOT NULL, consumption_json TEXT, opening_started INTEGER NOT NULL DEFAULT 0,
    UNIQUE(server_id,executor_id,attempt_id)
);
CREATE INDEX IF NOT EXISTS capacity_by_session ON execution_capacity_reservations(
    server_id,executor_id,session_id,state);
CREATE INDEX IF NOT EXISTS capacity_by_affinity ON execution_capacity_reservations(
    server_id,executor_id,affinity_key,state);
CREATE INDEX IF NOT EXISTS capacity_expiry ON execution_capacity_reservations(
    json_extract(request_json,'$.scope.boot_id'),deadline) WHERE state='HELD';
CREATE INDEX IF NOT EXISTS capacity_owner_generation ON execution_capacity_reservations(
    server_id,executor_id,json_extract(request_json,'$.scope.connection_generation')) WHERE state='HELD';
CREATE INDEX IF NOT EXISTS capacity_turn_operation ON execution_capacity_reservations(
    server_id,executor_id,json_extract(consumption_json,'$.turn_operation_id'));
CREATE INDEX IF NOT EXISTS capacity_open_operation ON execution_capacity_reservations(
    server_id,executor_id,json_extract(consumption_json,'$.opening_operation_id'));
CREATE TABLE IF NOT EXISTS execution_turn_slots (
    server_id TEXT NOT NULL, executor_id TEXT NOT NULL, session_id TEXT NOT NULL,
    operation_id TEXT NOT NULL, intent_hash TEXT NOT NULL, active INTEGER NOT NULL,
    PRIMARY KEY(server_id,executor_id,operation_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS active_execution_turn ON execution_turn_slots(
    server_id,executor_id,session_id) WHERE active=1;
CREATE TABLE IF NOT EXISTS capacity_operation_bindings (
    reservation_id TEXT NOT NULL, action TEXT NOT NULL,
    binding_json TEXT NOT NULL, core_intent_hash TEXT NOT NULL,
    PRIMARY KEY(reservation_id,action)
);
"""
ACTIVE = "('HELD','CONSUMED','RELEASE_PENDING','NEEDS_RECONCILIATION')"


def _revision(db):
    return db.execute('SELECT revision FROM capacity_revision WHERE singleton=1').fetchone()[0]


def _changed(db):
    db.execute('UPDATE capacity_revision SET revision=revision+1 WHERE singleton=1')
    return _revision(db)


def _row(db, request):
    s = request.scope
    cursor = db.execute('SELECT * FROM execution_capacity_reservations '
        'WHERE server_id=? AND executor_id=? AND attempt_id=?',
        (s.server_id, s.executor_id, request.attempt_id))
    value = cursor.fetchone()
    if value is None:
        return None
    row = dict(zip((c[0] for c in cursor.description), value))
    if CapacityRequest.from_dict(json.loads(row['request_json'])) != request:
        raise CoreError('RESERVATION_CONFLICT', 'capacity')
    return row


def _record(row, request, now, boot_id):
    remaining = 0
    if row['state'] == 'HELD' and request.scope.boot_id == boot_id:
        remaining = max(0, min(request.ttl_ms, int((row['deadline'] - now) * 1000)))
    consumption = row['consumption_json']
    return CapacityReservation(row['reservation_id'], request, row['state'], row['revision'],
        remaining, CapacityConsumption.from_dict(json.loads(consumption)) if consumption else None)


def _release_unconsumed(db, row, request, state):
    """Atomic proof: HELD cannot have crossed consumption or native admission."""
    if row['state'] != 'HELD' or row['consumption_json'] is not None or row['opening_started']:
        raise CoreError('NEEDS_RECONCILIATION', 'capacity_release')
    s = request.scope
    if request.unit == 'new_session':
        changed = db.execute('UPDATE owned_slot_reservations SET released=1 '
            'WHERE server_id=? AND executor_id=? AND session_id=? AND operation_id=? AND released=0',
            (s.server_id, s.executor_id, s.session_id, 'capacity:' + row['reservation_id'])).rowcount
        if changed != 1:
            raise CoreError('NEEDS_RECONCILIATION', 'capacity_release')
    db.execute('UPDATE execution_capacity_reservations SET state=?,revision=? WHERE reservation_id=?',
               (state, _changed(db), row['reservation_id']))


def _expire(db, row, request, now, boot_id):
    # A different boot cannot interpret the old monotonic deadline.
    if (row and row['state'] == 'HELD' and request.scope.boot_id == boot_id
            and now >= row['deadline']):
        _release_unconsumed(db, row, request, 'EXPIRED_UNCONSUMED')
        return _row(db, request)
    return row


def _reason(db, request, max_slots):
    s = request.scope
    if db.execute('SELECT 1 FROM execution_turn_slots WHERE server_id=? AND executor_id=? '
                  'AND session_id=? AND active=1', (s.server_id, s.executor_id, s.session_id)).fetchone():
        return 'BUSY_AFFINITY'
    if db.execute('SELECT 1 FROM execution_capacity_reservations WHERE server_id=? AND executor_id=? '
                  f'AND (session_id=? OR affinity_key=?) AND state IN {ACTIVE} LIMIT 1',
                  (s.server_id, s.executor_id, s.session_id, request.affinity_key)).fetchone():
        return 'BUSY_AFFINITY'
    slot = db.execute('SELECT released FROM owned_slot_reservations '
        'WHERE server_id=? AND executor_id=? AND session_id=?',
        (s.server_id, s.executor_id, s.session_id)).fetchone()
    if request.unit == 'next_turn':
        return 'AVAILABLE' if slot and not slot[0] else 'RECOVERING'
    if slot is not None:
        return 'RESERVATION_CONFLICT'
    occupied = db.execute('SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0').fetchone()[0]
    return 'HOST_FULL' if occupied >= max_slots else 'AVAILABLE'


class SQLiteCapacityOperations:
    """Internal mixin for SQLiteOwnedSlotLedger, using its worker and cap."""

    async def capacity_revision(self):
        """Installation change cursor, not a contextual availability decision."""
        def read(db):
            self._check_storage_identity(db)
            return _revision(db)
        return await self._run(read)

    async def _capacity_transaction(self, work):
        def run(db):
            self._check_storage_identity(db)
            db.execute('BEGIN IMMEDIATE')
            try:
                policy = db.execute('SELECT max_slots FROM owned_slot_policy WHERE singleton=1').fetchone()
                if policy is None:
                    db.execute('INSERT INTO owned_slot_policy VALUES(1,?)', (self.max_slots,))
                elif policy[0] != self.max_slots:
                    raise CoreError('PROFILE_DRIFT', 'capacity')
                result = work(db)
                db.execute('COMMIT')
                return result
            except BaseException:
                self._rollback_if_active(db)
                raise
        return await self._run(run)

    @staticmethod
    def _capacity_arguments(request, now, boot_id):
        if (type(request) is not CapacityRequest or type(now) not in (float, int)
                or not math.isfinite(now) or now < 0 or type(boot_id) is not str or not boot_id):
            raise ValueError('Invalid host capacity observation.')

    async def assess_capacity_slot(self, request, *, now, boot_id):
        self._capacity_arguments(request, now, boot_id)
        def work(db):
            reason = 'STALE_OBSERVATION' if request.scope.boot_id != boot_id else _reason(db, request, self.max_slots)
            return CapacityAssessment(CAPACITY_CONTRACT_REVISION, request.request_hash, reason, _revision(db), 100)
        return await self._capacity_transaction(work)

    async def capacity_reservation_page(self, server_id, executor_id, *,
                                         after_rowid=0, high_water_rowid=None, limit=128):
        """Public recovery facts for one namespace; no observation of free capacity.

        remaining_ms is deliberately zero: this history scan does not establish
        which monotonic clock owns a hold. Only the facade can assess validity.
        """
        from .journal import validate_claim_namespace, validate_claim_page
        validate_claim_namespace(server_id, executor_id)
        validate_claim_page(after_rowid, high_water_rowid, limit)
        def work(db):
            high = high_water_rowid
            if high is None:
                high = db.execute('SELECT COALESCE(MAX(rowid),0) FROM execution_capacity_reservations '
                    'WHERE server_id=? AND executor_id=?', (server_id, executor_id)).fetchone()[0]
            cursor = db.execute('SELECT rowid AS capacity_rowid,* FROM execution_capacity_reservations '
                f'WHERE server_id=? AND executor_id=? AND state IN {ACTIVE} AND rowid>? AND rowid<=? '
                'ORDER BY rowid LIMIT ?', (server_id, executor_id, after_rowid, high, limit + 1))
            names = [c[0] for c in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
            records = tuple(_record(row, CapacityRequest.from_dict(json.loads(row['request_json'])), 0, None)
                            for row in rows[:limit])
            return CapacityReservationPage(records, high, rows[limit - 1]['capacity_rowid'] if len(rows) > limit else None)
        return await self._capacity_transaction(work)

    async def release_fenced_capacity_holds(self, server_id, executor_id, *, connection_generation, limit=128):
        """Trusted current host owner only, AFTER fencing older connections.

        Atomic HELD + no consumption/transfer is proof of no native admission.
        This is cancellation by the replacement owner, not expiry and not a
        claim that consumed work or an old monotonic deadline is safe to free.
        """
        from .journal import validate_claim_namespace
        from .capacity import _integer
        validate_claim_namespace(server_id, executor_id)
        _integer(connection_generation, 'connection_generation', minimum=1)
        _integer(limit, 'limit', minimum=1, maximum=4096)
        def work(db):
            rows = db.execute('SELECT request_json FROM execution_capacity_reservations '
                "WHERE server_id=? AND executor_id=? AND state='HELD' "
                "AND json_extract(request_json,'$.scope.connection_generation')<? "
                'ORDER BY rowid LIMIT ?', (server_id, executor_id, connection_generation, limit)).fetchall()
            for (raw,) in rows:
                request = CapacityRequest.from_dict(json.loads(raw))
                _release_unconsumed(db, _row(db, request), request, 'RELEASED')
            return len(rows)
        return await self._capacity_transaction(work)

    async def expire_capacity_slots(self, *, now, boot_id, limit=128):
        """Bounded host maintenance; never expires another boot or consumed work."""
        if (type(now) not in (float, int) or not math.isfinite(now) or now < 0
                or type(boot_id) is not str or not boot_id
                or type(limit) is not int or not 1 <= limit <= 4096):
            raise ValueError('Invalid capacity expiry page.')
        def work(db):
            rows = db.execute('SELECT request_json FROM execution_capacity_reservations '
                "WHERE state='HELD' AND json_extract(request_json,'$.scope.boot_id')=? AND deadline<=? "
                'ORDER BY deadline,reservation_id LIMIT ?', (boot_id, now, limit)).fetchall()
            for (raw,) in rows:
                request = CapacityRequest.from_dict(json.loads(raw))
                _release_unconsumed(db, _row(db, request), request, 'EXPIRED_UNCONSUMED')
            return len(rows)
        return await self._capacity_transaction(work)

    async def reserve_capacity_slot(self, request, *, now, boot_id):
        self._capacity_arguments(request, now, boot_id)
        def work(db):
            old = _expire(db, _row(db, request), request, now, boot_id)
            if old:
                return _record(old, request, now, boot_id)
            reason = 'STALE_OBSERVATION' if request.scope.boot_id != boot_id else _reason(db, request, self.max_slots)
            if reason != 'AVAILABLE':
                return CapacityAssessment(CAPACITY_CONTRACT_REVISION, request.request_hash, reason, _revision(db), 100)
            s = request.scope
            identity = 'cap_' + uuid.uuid4().hex
            db.execute('INSERT INTO execution_capacity_reservations VALUES(?,?,?,?,?,?,?,?,?,?,NULL,0)',
                (identity, s.server_id, s.executor_id, request.attempt_id, s.session_id,
                 request.affinity_key, json.dumps(request.to_dict()), 'HELD', _changed(db), now + request.ttl_ms / 1000))
            if request.unit == 'new_session':
                db.execute('INSERT INTO owned_slot_reservations VALUES(?,?,?,?,0)',
                    (s.server_id, s.executor_id, s.session_id, 'capacity:' + identity))
            return _record(_row(db, request), request, now, boot_id)
        return await self._capacity_transaction(work)

    async def get_capacity_slot(self, request, *, now, boot_id):
        self._capacity_arguments(request, now, boot_id)
        def work(db):
            row = _expire(db, _row(db, request), request, now, boot_id)
            return _record(row, request, now, boot_id) if row else None
        return await self._capacity_transaction(work)

    async def consume_capacity_slot(self, request, reservation_id, consumption, *, now, boot_id):
        self._capacity_arguments(request, now, boot_id)
        # Validate the unit/operation relationship before touching the ledger.
        CapacityReservation(reservation_id, request, 'CONSUMED', 1, 0, consumption)
        def work(db):
            row = _expire(db, _row(db, request), request, now, boot_id)
            if not row or row['reservation_id'] != reservation_id:
                raise CoreError('RESERVATION_CONFLICT', 'capacity_consume')
            # Returning an expired record commits the expiry, but never consumes.
            if row['state'] == 'EXPIRED_UNCONSUMED':
                return _record(row, request, now, boot_id)
            if request.scope.boot_id != boot_id:
                raise CoreError('STALE_OBSERVATION', 'capacity_consume')
            if row['consumption_json']:
                if CapacityConsumption.from_dict(json.loads(row['consumption_json'])) != consumption:
                    raise CoreError('RESERVATION_CONFLICT', 'capacity_consume')
                return _record(row, request, now, boot_id)
            if row['state'] != 'HELD':
                raise CoreError('RESERVATION_CONFLICT', 'capacity_consume')
            # One canonical operation cannot be assigned to reservations for
            # different sessions/attempts, including opening-vs-turn aliases.
            ids = (consumption.turn_operation_id, consumption.opening_operation_id)
            if db.execute('SELECT 1 FROM execution_capacity_reservations WHERE server_id=? AND executor_id=? '
                    "AND (json_extract(consumption_json,'$.turn_operation_id') IN (?,?) "
                    "OR json_extract(consumption_json,'$.opening_operation_id') IN (?,?)) LIMIT 1",
                    (request.scope.server_id, request.scope.executor_id, *ids, *ids)).fetchone():
                raise CoreError('RESERVATION_CONFLICT', 'capacity_consume')
            db.execute('UPDATE execution_capacity_reservations SET state=?,consumption_json=?,revision=? '
                       'WHERE reservation_id=?', ('CONSUMED', json.dumps(consumption.to_dict()), _changed(db), reservation_id))
            return _record(_row(db, request), request, now, boot_id)
        return await self._capacity_transaction(work)

    async def capacity_for_operation(self, key, *, action, now, boot_id):
        """Find the durable reservation of this canonical operation, if any.

        The host must still bind/authorize it; this lookup grants no effect.
        Historical records remain discoverable to prevent operation reuse.
        """
        from .journal import validate_claim_namespace
        from .models import OperationKey
        if (not isinstance(key, OperationKey) or not key.operation_id
                or action not in ('runtime.open', 'turn.submit')
                or type(now) not in (int, float) or not math.isfinite(now) or now < 0
                or not isinstance(boot_id, str) or not boot_id):
            raise ValueError('Invalid capacity operation lookup.')
        validate_claim_namespace(key.server_id, key.executor_id)
        def work(db):
            matches = db.execute('SELECT request_json FROM execution_capacity_reservations '
                "WHERE server_id=? AND executor_id=? AND (json_extract(consumption_json,'$.turn_operation_id')=? "
                "OR json_extract(consumption_json,'$.opening_operation_id')=?) LIMIT 2",
                (key.server_id, key.executor_id, key.operation_id, key.operation_id)).fetchall()
            if not matches:
                return None
            if len(matches) != 1:
                raise CoreError('RESERVATION_CONFLICT', 'capacity_operation')
            request = CapacityRequest.from_dict(json.loads(matches[0][0]))
            row = _row(db, request)
            record = _record(row, request, now, boot_id)
            expected = (record.consumption.opening_operation_id if action == 'runtime.open'
                        else record.consumption.turn_operation_id)
            if expected != key.operation_id:
                raise CoreError('RESERVATION_CONFLICT', 'capacity_operation')
            return record
        return await self._capacity_transaction(work)

    async def release_capacity_slot(self, request, reservation_id, *, now, boot_id):
        self._capacity_arguments(request, now, boot_id)
        def work(db):
            row = _expire(db, _row(db, request), request, now, boot_id)
            if not row or row['reservation_id'] != reservation_id:
                raise CoreError('RESERVATION_CONFLICT', 'capacity_release')
            if row['state'] == 'HELD':
                _release_unconsumed(db, row, request, 'RELEASED')
            elif row['state'] in ('CONSUMED', 'NEEDS_RECONCILIATION'):
                db.execute('UPDATE execution_capacity_reservations SET state=?,revision=? WHERE reservation_id=?',
                           ('RELEASE_PENDING', _changed(db), reservation_id))
            return _record(_row(db, request), request, now, boot_id)
        return await self._capacity_transaction(work)

    async def bind_capacity_operation(self, request, reservation_id, binding, *, now, boot_id):
        """Bind the existing host receipt association, not a second intent.

        Consumption holds canonical R4 hashes. Prepared local opens also bind
        their selected binary/root and stream epoch; these hashes are different.
        Both hosts already persist this validated association before dispatch.
        """
        from .receipt_binding_r4 import validate_r4_receipt_binding
        self._capacity_arguments(request, now, boot_id)
        value = validate_r4_receipt_binding(binding)
        def work(db):
            row = _row(db, request)
            if (not row or row['reservation_id'] != reservation_id or not row['consumption_json']
                    or request.scope.boot_id != boot_id):
                raise CoreError('RESERVATION_CONFLICT', 'capacity_binding')
            c = CapacityConsumption.from_dict(json.loads(row['consumption_json']))
            source, action, scope = value['source'], value['action'], request.scope
            if action not in ('runtime.open', 'turn.submit'):
                raise CoreError('RESERVATION_CONFLICT', 'capacity_binding')
            expected = ((c.opening_operation_id, c.opening_intent_hash) if action == 'runtime.open'
                        else (c.turn_operation_id, c.turn_intent_hash))
            if (source['operation_id'], source['intent_hash']) != expected or any(
                    source[name] != getattr(scope, name) for name in (
                        'server_id', 'executor_id', 'agent_id', 'binding_id', 'session_id', 'connection_generation')):
                raise CoreError('RESERVATION_CONFLICT', 'capacity_binding')
            old = db.execute('SELECT binding_json FROM capacity_operation_bindings WHERE reservation_id=? AND action=?',
                             (reservation_id, action)).fetchone()
            if old:
                if json.loads(old[0]) != value:
                    raise CoreError('RESERVATION_CONFLICT', 'capacity_binding')
                # Retained metadata permits receipt replay after completion;
                # it is not permission to execute a released reservation.
                return
            if row['state'] != 'CONSUMED':
                raise CoreError('RESERVATION_CONFLICT', 'capacity_binding')
            db.execute('INSERT INTO capacity_operation_bindings VALUES(?,?,?,?)',
                       (reservation_id, action, json.dumps(value), value['core_intent_hash']))
            _changed(db)
        return await self._capacity_transaction(work)

    async def acquire_turn_slot(self, key, session_id, intent_hash):
        """Common gate for normal and reserved productive turns, before send.

        False means this operation was admitted already, including a terminal
        one. The caller must reconcile its receipt, never issue another send.
        """
        self._validate(key, session_id)
        from .capacity import _digest
        _digest(intent_hash, 'intent_hash')
        def work(db):
            prior = db.execute('SELECT session_id,intent_hash FROM execution_turn_slots '
                'WHERE server_id=? AND executor_id=? AND operation_id=?',
                (key.server_id, key.executor_id, key.operation_id)).fetchone()
            if prior:
                if tuple(prior) != (session_id, intent_hash):
                    raise CoreError('OPERATION_CONFLICT', 'turn_capacity')
                return False
            historic = db.execute('SELECT state,session_id,consumption_json FROM execution_capacity_reservations '
                "WHERE server_id=? AND executor_id=? AND (json_extract(consumption_json,'$.turn_operation_id')=? "
                "OR json_extract(consumption_json,'$.opening_operation_id')=?) LIMIT 2",
                (key.server_id, key.executor_id, key.operation_id, key.operation_id)).fetchall()
            if historic:
                if len(historic) != 1:
                    raise CoreError('RESERVATION_CONFLICT', 'turn_capacity')
                state, reserved_session, raw = historic[0]
                c = CapacityConsumption.from_dict(json.loads(raw))
                if (state != 'CONSUMED' or reserved_session != session_id or c.turn_operation_id != key.operation_id):
                    # An operation assigned to an old/cancelled reservation
                    # must never silently reenter as ordinary unreserved work.
                    raise CoreError('RESERVATION_CONFLICT', 'turn_capacity')
            slot = db.execute('SELECT released,operation_id FROM owned_slot_reservations WHERE server_id=? AND executor_id=? '
                              'AND session_id=?', (key.server_id, key.executor_id, session_id)).fetchone()
            if not slot or slot[0] or slot[1].startswith('capacity:'):
                raise CoreError('NEEDS_RECONCILIATION', 'turn_capacity')
            occupied = db.execute('SELECT 1 FROM execution_turn_slots WHERE server_id=? AND executor_id=? '
                'AND session_id=? AND active=1', (key.server_id, key.executor_id, session_id)).fetchone()
            reserved = db.execute('SELECT state,consumption_json,reservation_id FROM execution_capacity_reservations '
                f'WHERE server_id=? AND executor_id=? AND session_id=? AND state IN {ACTIVE}',
                (key.server_id, key.executor_id, session_id)).fetchall()
            if occupied:
                raise CoreError('CAPACITY_EXCEEDED', 'turn_capacity', retry_safe=True)
            for state, raw, identity in reserved:
                c = CapacityConsumption.from_dict(json.loads(raw)) if raw else None
                local_hash = _bound_hash(db, identity, 'turn.submit')
                if state != 'CONSUMED' or c is None or (c.turn_operation_id, local_hash) != (key.operation_id, intent_hash):
                    raise CoreError('CAPACITY_EXCEEDED', 'turn_capacity', retry_safe=True)
            db.execute('INSERT INTO execution_turn_slots VALUES(?,?,?,?,?,1)',
                       (key.server_id, key.executor_id, session_id, key.operation_id, intent_hash))
            _changed(db)
            return True
        return await self._capacity_transaction(work)

    async def finish_turn_slot(self, key, session_id):
        """Trusted Core only: correlated native terminal or proven no effect."""
        self._validate(key, session_id)
        def work(db):
            changed = db.execute('UPDATE execution_turn_slots SET active=0 WHERE server_id=? AND executor_id=? '
                'AND session_id=? AND operation_id=? AND active=1',
                (key.server_id, key.executor_id, session_id, key.operation_id)).rowcount
            if changed:
                release_session_capacity(db, key.server_id, key.executor_id, session_id, turn_id=key.operation_id)
                _changed(db)
            return bool(changed)
        return await self._capacity_transaction(work)


def transfer_reserved_open(db, key, session_id, intent_hash):
    """Take the existing physical slot once; opening retains the first turn."""
    rows = db.execute('SELECT reservation_id,state,consumption_json,opening_started '
        f'FROM execution_capacity_reservations WHERE server_id=? AND executor_id=? AND session_id=? AND state IN {ACTIVE}',
        (key.server_id, key.executor_id, session_id)).fetchall()
    if not rows:
        return False
    for identity, state, raw, started in rows:
        c = CapacityConsumption.from_dict(json.loads(raw)) if raw else None
        local_hash = _bound_hash(db, identity, 'runtime.open')
        if (state != 'CONSUMED' or not c or started or
                (c.opening_operation_id, local_hash) != (key.operation_id, intent_hash) or local_hash is None):
            raise CoreError('CAPACITY_EXCEEDED', 'slot_ledger', retry_safe=True)
        count = db.execute('UPDATE owned_slot_reservations SET operation_id=? WHERE server_id=? AND executor_id=? '
            'AND session_id=? AND operation_id=? AND released=0',
            (key.operation_id, key.server_id, key.executor_id, session_id, 'capacity:' + identity)).rowcount
        if count != 1:
            raise CoreError('NEEDS_RECONCILIATION', 'slot_ledger')
        db.execute('UPDATE execution_capacity_reservations SET opening_started=1,revision=? WHERE reservation_id=?',
                   (_changed(db), identity))
    return True


def _bound_hash(db, identity, action):
    row = db.execute('SELECT core_intent_hash FROM capacity_operation_bindings WHERE reservation_id=? AND action=?',
                     (identity, action)).fetchone()
    return row[0] if row else None


def release_session_capacity(db, server_id, executor_id, session_id, *, turn_id=None):
    """Called only after the physical owner proves stop or a correlated turn ends."""
    rows = db.execute('SELECT reservation_id,consumption_json FROM execution_capacity_reservations '
        f'WHERE server_id=? AND executor_id=? AND session_id=? AND state IN {ACTIVE}',
        (server_id, executor_id, session_id)).fetchall()
    for identity, raw in rows:
        c = CapacityConsumption.from_dict(json.loads(raw)) if raw else None
        if turn_id is None or c and c.turn_operation_id == turn_id:
            db.execute('UPDATE execution_capacity_reservations SET state=?,revision=? WHERE reservation_id=?',
                       ('RELEASED', _changed(db), identity))
    if turn_id is None:
        db.execute('UPDATE execution_turn_slots SET active=0 WHERE server_id=? AND executor_id=? AND session_id=?',
                   (server_id, executor_id, session_id))
