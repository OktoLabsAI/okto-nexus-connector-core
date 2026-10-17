"""Bounded immutable journal creation registrations in the host slot store.

This registry alone does not establish an audit frontier. Consumers must retain
their existing startup audit until creation discipline and conversion qualify.
"""
import hashlib
import json
import re

from .journal_locations import (JournalLocation, JournalRegistration,
                                JournalLocationPage, JournalRegistryHead,
                                JournalAuditAnchor,
                                validate_journal_name)
from .models import CoreError, SessionKey
from .journal import validate_claim_page


SCHEMA = '''
CREATE TABLE IF NOT EXISTS managed_journal_locations (
    revision INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    server_id TEXT,
    executor_id TEXT,
    session_id TEXT,
    CHECK ((server_id IS NULL AND executor_id IS NULL AND session_id IS NULL)
        OR (server_id IS NOT NULL AND executor_id IS NOT NULL AND session_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS managed_store_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    store_id TEXT NOT NULL UNIQUE
);
CREATE UNIQUE INDEX IF NOT EXISTS managed_journal_session_location
    ON managed_journal_locations(server_id,executor_id,session_id)
    WHERE session_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS managed_journal_head (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    revision INTEGER NOT NULL CHECK(revision>=0),
    digest TEXT NOT NULL,
    complete INTEGER NOT NULL CHECK(complete IN (0,1))
);
CREATE TABLE IF NOT EXISTS managed_journal_audit_anchor (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    nonce TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=0),
    digest TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS managed_journal_locations_no_update
    BEFORE UPDATE ON managed_journal_locations
    BEGIN SELECT RAISE(ABORT, 'journal registration is immutable'); END;
CREATE TRIGGER IF NOT EXISTS managed_journal_locations_no_delete
    BEFORE DELETE ON managed_journal_locations
    BEGIN SELECT RAISE(ABORT, 'journal registration is immutable'); END;
'''

EMPTY_DIGEST = '0' * 64


def _extend_digest(digest, record):
    location = record.location
    scope = location.session
    payload = json.dumps([record.revision, location.name,
        scope.server_id if scope else None,
        scope.executor_id if scope else None,
        scope.session_id if scope else None], ensure_ascii=True,
        separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(bytes.fromhex(digest) + payload).hexdigest()


def _head(db):
    identity = db.execute('SELECT store_id FROM managed_store_identity WHERE singleton=1').fetchone()
    row = db.execute('SELECT revision,digest,complete FROM managed_journal_head WHERE singleton=1').fetchone()
    if (identity is None or row is None or type(row[0]) is not int or row[0] < 0
            or type(row[1]) is not str or re.fullmatch('[0-9a-f]{64}', row[1]) is None
            or row[2] not in (0, 1)
            or (row[0] == 0 and row[1] != EMPTY_DIGEST)):
        raise CoreError('JOURNAL_UNAVAILABLE', 'journal_registry')
    high = db.execute('SELECT COALESCE(MAX(revision),0) FROM managed_journal_locations').fetchone()[0]
    if row[0] > high or (row[2] == 1 and row[0] != high):
        raise CoreError('PROFILE_DRIFT', 'journal_registry')
    return JournalRegistryHead(identity[0], row[0], row[1], bool(row[2]))


def _anchor(db, head):
    row = db.execute('SELECT nonce,revision,digest FROM managed_journal_audit_anchor '
        'WHERE singleton=1').fetchone()
    if row is None:
        return None
    if (type(row[0]) is not str or re.fullmatch('audit_[0-9a-f]{32}', row[0]) is None
            or type(row[1]) is not int or row[1] < 0 or row[1] > head.revision
            or type(row[2]) is not str or re.fullmatch('[0-9a-f]{64}', row[2]) is None
            or (row[1] == 0 and row[2] != EMPTY_DIGEST)
            or (row[1] == head.revision and row[2] != head.digest)):
        raise CoreError('PROFILE_DRIFT', 'journal_audit_anchor')
    return JournalAuditAnchor(head.store_id, row[0], row[1], row[2])


def registration(row):
    if row is None:
        return None
    revision, name, server_id, executor_id, session_id = row
    try:
        if type(revision) is not int or revision < 1:
            raise ValueError('Invalid journal revision.')
        scope = (server_id, executor_id, session_id)
        if any(value is None for value in scope) and scope != (None, None, None):
            raise ValueError('Incomplete journal scope.')
        return JournalRegistration(JournalLocation(name,
            SessionKey(*scope) if session_id is not None else None), revision)
    except ValueError as exc:
        raise CoreError('JOURNAL_UNAVAILABLE', 'journal_registry') from exc


class SQLiteJournalLocationRegistry:
    async def journal_audit_anchor(self):
        """Read the Core half of a host-owned two-store audit handshake."""
        def read(db):
            self._check_storage_identity(db)
            return _anchor(db, _head(db))
        return await self._run(read)

    async def stage_journal_audit_anchor(self, *, nonce, head):
        """Persist an audit token only at the exact complete registry head.

        The trusted host must finish its physical audit before calling this.
        Staging alone never authorizes bypassing the startup directory scan.
        """
        if (type(nonce) is not str or re.fullmatch('audit_[0-9a-f]{32}', nonce) is None
                or type(head) is not JournalRegistryHead):
            raise ValueError('Invalid journal audit anchor.')
        def write(db):
            self._check_storage_identity(db)
            db.execute('BEGIN IMMEDIATE')
            try:
                current = _head(db)
                if not current.complete or current != head:
                    raise CoreError('PROFILE_DRIFT', 'journal_audit_anchor')
                anchor = _anchor(db, current)
                result = JournalAuditAnchor(current.store_id, nonce,
                                            current.revision, current.digest)
                if anchor != result:
                    db.execute('INSERT INTO managed_journal_audit_anchor '
                        '(singleton,nonce,revision,digest) VALUES(1,?,?,?) '
                        'ON CONFLICT(singleton) DO UPDATE SET nonce=excluded.nonce, '
                        'revision=excluded.revision,digest=excluded.digest',
                        (nonce, current.revision, current.digest))
                db.execute('COMMIT')
                return result
            except BaseException:
                self._rollback_if_active(db)
                raise
        return await self._run(write)

    async def journal_registry_head(self):
        """Read the durable frontier; incomplete heads cannot authorize audit elision."""
        def read(db):
            self._check_storage_identity(db)
            return _head(db)
        return await self._run(read)

    async def advance_journal_registry_head(self, *, limit=128):
        """Convert existing registrations in bounded, resumable transactions."""
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError('Journal head advance limit must be from 1 to 128.')
        def advance(db):
            self._check_storage_identity(db)
            db.execute('BEGIN IMMEDIATE')
            try:
                head = _head(db)
                if head.complete:
                    db.execute('COMMIT')
                    return head
                rows = db.execute('SELECT * FROM managed_journal_locations WHERE revision>? '
                    'ORDER BY revision LIMIT ?', (head.revision, limit + 1)).fetchall()
                digest = head.digest
                revision = head.revision
                for row in rows[:limit]:
                    record = registration(row)
                    digest = _extend_digest(digest, record)
                    revision = record.revision
                complete = len(rows) <= limit
                db.execute('UPDATE managed_journal_head SET revision=?,digest=?,complete=? '
                    'WHERE singleton=1', (revision, digest, int(complete)))
                result = JournalRegistryHead(head.store_id, revision, digest, complete)
                db.execute('COMMIT')
                return result
            except BaseException:
                self._rollback_if_active(db)
                raise
        return await self._run(advance)

    async def physical_store_id(self):
        """Durable ledger identity for a host-owned cross-store audit binding.

        This identifies the ledger, not the other physical journals or an
        audit frontier. A host must bind and verify it against its own state.
        """
        def read(db):
            self._check_storage_identity(db)
            row = db.execute('SELECT store_id FROM managed_store_identity WHERE singleton=1').fetchone()
            if (row is None or type(row[0]) is not str or not row[0].startswith('store_')
                    or len(row[0]) != 38
                    or any(char not in '0123456789abcdef' for char in row[0][6:])):
                raise CoreError('JOURNAL_UNAVAILABLE', 'journal_registry')
            return row[0]
        return await self._run(read)

    async def register_journal_locations(self, locations):
        if type(locations) is not tuple or not 1 <= len(locations) <= 128 or any(
                type(location) is not JournalLocation for location in locations):
            raise ValueError('Journal registration batch must contain 1 to 128 locations.')
        def write(db):
            self._check_storage_identity(db)
            db.execute('BEGIN IMMEDIATE')
            try:
                head = _head(db)
                digest = head.digest
                revision = head.revision
                result = []
                for location in locations:
                    previous = registration(db.execute('SELECT * FROM managed_journal_locations WHERE name=?',
                        (location.name,)).fetchone())
                    if previous is not None:
                        if previous.location != location:
                            raise CoreError('PROFILE_DRIFT', 'journal_registry')
                        result.append(previous)
                        continue
                    scope = location.session
                    identity = (scope.server_id, scope.executor_id, scope.session_id) if scope else (None, None, None)
                    if scope and db.execute('SELECT 1 FROM managed_journal_locations '
                            'WHERE server_id=? AND executor_id=? AND session_id=?', identity).fetchone():
                        raise CoreError('PROFILE_DRIFT', 'journal_registry')
                    cursor = db.execute('INSERT INTO managed_journal_locations(name,server_id,executor_id,session_id) '
                        'VALUES(?,?,?,?)', (location.name, *identity))
                    record = JournalRegistration(location, cursor.lastrowid)
                    result.append(record)
                    if head.complete:
                        digest = _extend_digest(digest, record)
                        revision = record.revision
                if head.complete and revision != head.revision:
                    db.execute('UPDATE managed_journal_head SET revision=?,digest=? WHERE singleton=1',
                               (revision, digest))
                db.execute('COMMIT')
                return tuple(result)
            except BaseException:
                self._rollback_if_active(db)
                raise
        return await self._run(write)

    async def journal_location(self, name):
        validate_journal_name(name)
        def read(db):
            self._check_storage_identity(db)
            return registration(db.execute('SELECT * FROM managed_journal_locations WHERE name=?', (name,)).fetchone())
        return await self._run(read)

    async def journal_location_page(self, *, after_revision=0, high_water_revision=None, limit=128):
        validate_claim_page(after_revision, high_water_revision, limit, label='journal-location')
        if limit > 128:
            raise ValueError('Journal location page exceeds its budget.')
        def read(db):
            self._check_storage_identity(db)
            high = high_water_revision
            if high is None:
                high = db.execute('SELECT COALESCE(MAX(revision),0) FROM managed_journal_locations').fetchone()[0]
            rows = db.execute('SELECT * FROM managed_journal_locations WHERE revision>? AND revision<=? '
                'ORDER BY revision LIMIT ?', (after_revision, high, limit + 1)).fetchall()
            records = tuple(registration(row) for row in rows[:limit])
            return JournalLocationPage(records, high,
                records[-1].revision if len(rows) > limit else None)
        return await self._run(read)
