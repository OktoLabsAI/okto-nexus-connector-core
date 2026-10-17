"""Registry SQL and storage cost, separately from session journal contents."""
import asyncio
import hashlib

import pytest

from nexus_connector_core import JournalLocation, SessionKey, SQLiteOwnedSlotLedger


def location(index):
    session = f'ses_{index:032x}'
    executor = 'exe_' + 'b' * 32
    digest = hashlib.sha256((executor + '\0' + session).encode('ascii')).hexdigest()
    return JournalLocation(f'session-{digest}.db',
        SessionKey('srv_' + 'a' * 32, executor, session))


@pytest.mark.parametrize('count', [1_000, 10_000, 100_000])
def test_registry_cost_is_bounded_per_lookup_or_page(tmp_path, count, record_property):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'owned-slots.db')
        try:
            before = await ledger.capacity_revision()
            for start in range(0, count, 128):
                records = await ledger.register_journal_locations(tuple(
                    location(index) for index in range(start, min(start + 128, count))))
                assert records[-1].revision == min(start + 128, count)
            assert await ledger.capacity_revision() == before
            assert not (await ledger.owned_slot_page()).reservations

            steps = [0]
            def progress():
                steps[0] += 1
                return 0
            async def observe(operation, label, limit):
                steps[0] = 0
                await ledger._run(lambda db: db.set_progress_handler(progress, 1))
                try:
                    result = await operation()
                finally:
                    await ledger._run(lambda db: db.set_progress_handler(None, 0))
                record_property(label + '_vm_steps', steps[0])
                assert steps[0] < limit, (label, steps[0])
                return result
            last = location(count - 1)
            head = await observe(lambda: ledger.journal_registry_head(), 'registry_head', 500)
            assert head.complete and head.revision == count
            found = await observe(lambda: ledger.journal_location(last.name), 'exact_lookup', 500)
            assert found.location == last and found.revision == count
            page = await observe(lambda: ledger.journal_location_page(after_revision=count - 129),
                                 'page_with_snapshot', 5_000)
            assert len(page.registrations) == 128 and page.high_water_revision == count
            assert page.next_after_revision == count - 1
            tail = await observe(lambda: ledger.journal_location_page(
                after_revision=page.next_after_revision, high_water_revision=page.high_water_revision),
                'tail_page', 500)
            assert tail.registrations == (found,) and tail.next_after_revision is None
            # SQLite allocated pages are deterministic storage accounting;
            # WAL size and wall time depend on checkpointing and machine load.
            allocated = await ledger._run(lambda db:
                db.execute('PRAGMA page_count').fetchone()[0] *
                db.execute('PRAGMA page_size').fetchone()[0])
            record_property('journal_locations', count)
            record_property('allocated_bytes', allocated)
            record_property('allocated_bytes_per_location', allocated / count)
            record_property('default_storage_limit_bytes', ledger.max_storage_bytes)
            assert allocated < ledger.max_storage_bytes
        finally:
            await ledger.aclose()
    asyncio.run(run())
