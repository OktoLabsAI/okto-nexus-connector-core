"""Physical registration is durable intent, never native ownership or audit proof."""
import asyncio
import sqlite3
import threading

import pytest

from nexus_connector_core import (CoreError, JournalAuditAnchor, JournalRegistryHead,
    JournalLocation, SessionKey, SQLiteOwnedSlotLedger,
    require_audit_snapshot_not_rolled_back)


def location(index):
    return JournalLocation(f'session-{index}.db', SessionKey('server', 'executor', f'session-{index}'))


def test_physical_store_id_is_durable_and_unique_to_the_ledger(tmp_path):
    async def run():
        path = tmp_path / 'owned-slots.db'
        first = SQLiteOwnedSlotLedger(path)
        second = None
        try:
            store_id = await first.physical_store_id()
            assert store_id.startswith('store_') and len(store_id) == 38
            second = SQLiteOwnedSlotLedger(path)
            assert await second.physical_store_id() == store_id
            first.close()
            first = SQLiteOwnedSlotLedger(path)
            assert await first.physical_store_id() == store_id
            fresh = SQLiteOwnedSlotLedger(tmp_path / 'another-ledger.db')
            try:
                assert await fresh.physical_store_id() != store_id
            finally:
                fresh.close()
        finally:
            first.close()
            if second is not None:
                second.close()
    asyncio.run(run())


def test_existing_registered_ledger_acquires_id_without_losing_history(tmp_path):
    path = tmp_path / 'owned-slots.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE managed_journal_locations ('
            'revision INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, '
            'server_id TEXT, executor_id TEXT, session_id TEXT)')
        db.execute('INSERT INTO managed_journal_locations '
            '(name,server_id,executor_id,session_id) VALUES(?,?,?,?)',
            ('session-1.db', 'server', 'executor', 'session-1'))

    async def run():
        ledger = SQLiteOwnedSlotLedger(path)
        try:
            assert (await ledger.physical_store_id()).startswith('store_')
            assert (await ledger.journal_location('session-1.db')).location == location(1)
        finally:
            ledger.close()
    asyncio.run(run())


def test_registry_head_tracks_committed_registrations_and_survives_reopen(tmp_path):
    async def run():
        path = tmp_path / 'owned-slots.db'
        ledger = SQLiteOwnedSlotLedger(path)
        try:
            empty = await ledger.journal_registry_head()
            assert empty.complete and empty.revision == 0 and empty.digest == '0' * 64
            assert empty.store_id == await ledger.physical_store_id()
            records = await ledger.register_journal_locations((location(1), location(2)))
            head = await ledger.journal_registry_head()
            assert head.complete and head.revision == records[-1].revision
            assert head.digest != empty.digest
            assert await ledger.register_journal_locations((location(1), location(2))) == records
            assert await ledger.journal_registry_head() == head
            with pytest.raises(CoreError, match='PROFILE_DRIFT'):
                await ledger.register_journal_locations((location(3),
                    JournalLocation('session-1.db', location(3).session)))
            assert await ledger.journal_registry_head() == head
            ledger.close()
            ledger = SQLiteOwnedSlotLedger(path)
            assert await ledger.journal_registry_head() == head
            assert await ledger.advance_journal_registry_head() == head
        finally:
            ledger.close()
    asyncio.run(run())


def test_legacy_registry_head_conversion_is_bounded_and_resumable(tmp_path):
    path = tmp_path / 'owned-slots.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE managed_journal_locations ('
            'revision INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, '
            'server_id TEXT, executor_id TEXT, session_id TEXT)')
        for index in range(5):
            db.execute('INSERT INTO managed_journal_locations '
                '(name,server_id,executor_id,session_id) VALUES(?,?,?,?)',
                (f'session-{index}.db', 'server', 'executor', f'session-{index}'))

    async def run():
        ledger = SQLiteOwnedSlotLedger(path)
        try:
            assert not (await ledger.journal_registry_head()).complete
            first = await ledger.advance_journal_registry_head(limit=2)
            assert first.revision == 2 and not first.complete
            await ledger.register_journal_locations((location(5),))
            assert (await ledger.journal_registry_head()).revision == 2
            ledger.close()
            ledger = SQLiteOwnedSlotLedger(path)
            assert await ledger.journal_registry_head() == first
            second = await ledger.advance_journal_registry_head(limit=2)
            assert second.revision == 4 and not second.complete
            final = await ledger.advance_journal_registry_head(limit=2)
            assert final.revision == 6 and final.complete
            await ledger.register_journal_locations((location(6),))
            assert (await ledger.journal_registry_head()).revision == 7
            with pytest.raises(ValueError):
                await ledger.advance_journal_registry_head(limit=129)
        finally:
            ledger.close()
    asyncio.run(run())


def test_registry_head_rejects_missing_registration_and_immutable_mutations(tmp_path):
    async def run():
        path = tmp_path / 'owned-slots.db'
        ledger = SQLiteOwnedSlotLedger(path)
        try:
            await ledger.register_journal_locations((location(1),))
            with sqlite3.connect(path) as db:
                with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                    db.execute('DELETE FROM managed_journal_locations WHERE revision=1')
                with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                    db.execute('UPDATE managed_journal_locations SET name=? WHERE revision=1',
                               ('different.db',))
                db.execute('DROP TRIGGER managed_journal_locations_no_delete')
                db.execute('DELETE FROM managed_journal_locations WHERE revision=1')
            with pytest.raises(CoreError, match='PROFILE_DRIFT'):
                await ledger.journal_registry_head()
        finally:
            ledger.close()
    asyncio.run(run())


def test_audit_anchor_is_staged_only_for_complete_exact_head(tmp_path):
    async def run():
        path = tmp_path / 'owned-slots.db'
        ledger = SQLiteOwnedSlotLedger(path)
        try:
            assert await ledger.journal_audit_anchor() is None
            initial = await ledger.journal_registry_head()
            token = 'audit_' + 'a' * 32
            anchor = await ledger.stage_journal_audit_anchor(nonce=token, head=initial)
            assert (anchor.store_id, anchor.nonce, anchor.revision, anchor.digest) == (
                initial.store_id, token, initial.revision, initial.digest)
            assert await ledger.stage_journal_audit_anchor(nonce=token, head=initial) == anchor
            await ledger.register_journal_locations((location(1),))
            assert await ledger.journal_audit_anchor() == anchor
            with pytest.raises(CoreError, match='PROFILE_DRIFT'):
                await ledger.stage_journal_audit_anchor(nonce=token, head=initial)
            current = await ledger.journal_registry_head()
            replacement = await ledger.stage_journal_audit_anchor(
                nonce='audit_' + 'b' * 32, head=current)
            assert replacement.revision == 1 and replacement != anchor
            ledger.close()
            ledger = SQLiteOwnedSlotLedger(path)
            assert await ledger.journal_audit_anchor() == replacement
            with pytest.raises(ValueError):
                await ledger.stage_journal_audit_anchor(nonce='bad', head=current)
        finally:
            ledger.close()
    asyncio.run(run())


def test_incomplete_legacy_registry_cannot_stage_audit_anchor(tmp_path):
    path = tmp_path / 'owned-slots.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE managed_journal_locations ('
            'revision INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, '
            'server_id TEXT, executor_id TEXT, session_id TEXT)')
        db.execute('INSERT INTO managed_journal_locations '
            '(name,server_id,executor_id,session_id) VALUES(?,?,?,?)',
            ('session-1.db', 'server', 'executor', 'session-1'))

    async def run():
        ledger = SQLiteOwnedSlotLedger(path)
        try:
            incomplete = await ledger.journal_registry_head()
            assert not incomplete.complete
            with pytest.raises(CoreError, match='PROFILE_DRIFT'):
                await ledger.stage_journal_audit_anchor(
                    nonce='audit_' + 'a' * 32, head=incomplete)
            complete = await ledger.advance_journal_registry_head()
            assert complete.complete
            assert (await ledger.stage_journal_audit_anchor(
                nonce='audit_' + 'a' * 32, head=complete)).revision == 1
        finally:
            ledger.close()
    asyncio.run(run())


def test_host_snapshot_fences_definite_core_rollback_but_allows_forward_head():
    store_id = 'store_' + 'a' * 32
    host = JournalAuditAnchor(store_id, 'audit_' + 'b' * 32, 3, 'c' * 64)
    same = JournalAuditAnchor(store_id, 'audit_' + 'd' * 32, 3, 'c' * 64)
    require_audit_snapshot_not_rolled_back(host, same,
        JournalRegistryHead(store_id, 3, 'c' * 64, True))
    require_audit_snapshot_not_rolled_back(host, same,
        JournalRegistryHead(store_id, 4, 'e' * 64, True))
    for core, head in (
        (None, JournalRegistryHead(store_id, 3, 'c' * 64, True)),
        (same, JournalRegistryHead(store_id, 2, 'c' * 64, True)),
        (same, JournalRegistryHead(store_id, 3, 'e' * 64, True)),
        (same, JournalRegistryHead(store_id, 3, 'c' * 64, False)),
        (JournalAuditAnchor(store_id, same.nonce, 2, 'c' * 64),
            JournalRegistryHead(store_id, 4, 'e' * 64, True)),
    ):
        with pytest.raises(CoreError, match='PROFILE_DRIFT'):
            require_audit_snapshot_not_rolled_back(host, core, head)


def test_registration_is_immutable_idempotent_and_independent_of_capacity(tmp_path):
    async def run():
        path = tmp_path / 'owned-slots.db'
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            before = await ledger.capacity_revision()
            items = (location(1), JournalLocation('executor-journal.db'))
            records = await ledger.register_journal_locations(items)
            assert [r.revision for r in records] == [1, 2]
            assert await ledger.register_journal_locations(items) == records
            assert await ledger.capacity_revision() == before
            assert not (await ledger.owned_slot_page()).reservations
            assert not (tmp_path / items[0].name).exists()
            ledger.close()
            ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
            assert await ledger.journal_location(items[0].name) == records[0]
            assert await ledger.journal_location(items[1].name) == records[1]
            assert await ledger.journal_location('absent.db') is None
        finally:
            ledger.close()
    asyncio.run(run())


def test_conflicting_batch_rolls_back_every_new_location(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'owned-slots.db')
        try:
            first, = await ledger.register_journal_locations((location(1),))
            conflicts = (JournalLocation('session-1.db'),
                         JournalLocation('renamed.db', location(1).session),
                         JournalLocation('session-1.db', location(2).session))
            for conflict in conflicts:
                with pytest.raises(CoreError, match='PROFILE_DRIFT'):
                    await ledger.register_journal_locations((location(2), conflict))
                assert await ledger.journal_location(location(2).name) is None
                assert (await ledger.journal_location_page()).registrations == (first,)
            second, = await ledger.register_journal_locations((location(2),))
            assert second.revision == 2
        finally:
            ledger.close()
    asyncio.run(run())


def test_snapshot_pages_exclude_later_registrations_and_bound_reads(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'owned-slots.db')
        try:
            initial = await ledger.register_journal_locations(tuple(location(i) for i in range(3)))
            first = await ledger.journal_location_page(limit=2)
            assert first.registrations == initial[:2]
            assert first.next_after_revision == 2 and first.high_water_revision == 3
            await ledger.register_journal_locations((location(3),))
            second = await ledger.journal_location_page(after_revision=first.next_after_revision,
                high_water_revision=first.high_water_revision, limit=2)
            assert second.registrations == initial[2:] and second.next_after_revision is None
            assert len((await ledger.journal_location_page()).registrations) == 4
            for kwargs in ({'limit': 129}, {'limit': True}, {'after_revision': -1},
                           {'after_revision': 3, 'high_water_revision': 2}):
                with pytest.raises(ValueError):
                    await ledger.journal_location_page(**kwargs)
        finally:
            ledger.close()
    asyncio.run(run())


def test_two_store_connections_cannot_assign_one_session_to_two_files(tmp_path):
    async def run():
        first = SQLiteOwnedSlotLedger(tmp_path / 'owned-slots.db')
        second = SQLiteOwnedSlotLedger(tmp_path / 'owned-slots.db')
        try:
            results = await asyncio.gather(
                first.register_journal_locations((location(1),)),
                second.register_journal_locations((JournalLocation('other.db', location(1).session),)),
                return_exceptions=True)
            assert sum(isinstance(result, CoreError) for result in results) == 1
            assert len((await first.journal_location_page()).registrations) == 1
        finally:
            first.close()
            second.close()
    asyncio.run(run())


def test_cancelled_observer_does_not_erase_started_registration(tmp_path):
    async def run():
        path = tmp_path / 'owned-slots.db'
        ledger = SQLiteOwnedSlotLedger(path)
        lock = None
        try:
            await ledger.register_journal_locations((location(0),))
            entered = threading.Event()
            original = ledger._check_storage_identity
            def observe(db):
                original(db)
                entered.set()
            ledger._check_storage_identity = observe
            lock = sqlite3.connect(path, isolation_level=None)
            lock.execute('BEGIN IMMEDIATE')
            task = asyncio.create_task(ledger.register_journal_locations((location(1),)))
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            lock.execute('ROLLBACK')
            lock.close()
            lock = None
            result = await ledger.journal_location(location(1).name)
            assert result is not None
            assert await ledger.register_journal_locations((location(1),)) == (result,)
        finally:
            if lock is not None:
                lock.close()
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('name', ['../file.db', 'C:/file.db', 'CON.db', 'con.db',
                                'owned-slots.db', 'alias.DB', 'file.db-wal'])
def test_nonportable_or_reserved_names_are_rejected(name):
    with pytest.raises(ValueError):
        JournalLocation(name)


def test_storage_full_rolls_back_batch_without_losing_existing_intent(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'owned-slots.db')
        try:
            first, = await ledger.register_journal_locations((location(0),))
            def exhaust_growth(db):
                pages = db.execute('PRAGMA page_count').fetchone()[0]
                db.execute(f'PRAGMA max_page_count={pages}')
            await ledger._run(exhaust_growth)
            with pytest.raises(sqlite3.OperationalError, match='full'):
                await ledger.register_journal_locations(tuple(
                    JournalLocation(f'session-{i}-' + 'a' * 90 + '.db',
                        SessionKey('server', 'executor', f'session-{i}')) for i in range(1, 129)))
            assert (await ledger.journal_location_page()).registrations == (first,)
            assert await ledger.journal_location(first.location.name) == first
            assert not (await ledger.owned_slot_page()).reservations
        finally:
            ledger.close()
    asyncio.run(run())
