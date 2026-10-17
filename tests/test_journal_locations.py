"""Physical registration is durable intent, never native ownership or audit proof."""
import asyncio
import sqlite3
import threading

import pytest

from nexus_connector_core import CoreError, JournalLocation, SessionKey, SQLiteOwnedSlotLedger


def location(index):
    return JournalLocation(f'session-{index}.db', SessionKey('server', 'executor', f'session-{index}'))


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
