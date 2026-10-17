"""Bounded immutable journal creation registrations in the host slot store.

This registry alone does not establish an audit frontier. Consumers must retain
their existing startup audit until creation discipline and conversion qualify.
"""
from .journal_locations import (JournalLocation, JournalRegistration,
                                JournalLocationPage, validate_journal_name)
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
CREATE UNIQUE INDEX IF NOT EXISTS managed_journal_session_location
    ON managed_journal_locations(server_id,executor_id,session_id)
    WHERE session_id IS NOT NULL;
'''


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
    async def register_journal_locations(self, locations):
        if type(locations) is not tuple or not 1 <= len(locations) <= 128 or any(
                type(location) is not JournalLocation for location in locations):
            raise ValueError('Journal registration batch must contain 1 to 128 locations.')
        def write(db):
            self._check_storage_identity(db)
            db.execute('BEGIN IMMEDIATE')
            try:
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
                    result.append(JournalRegistration(location, cursor.lastrowid))
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
