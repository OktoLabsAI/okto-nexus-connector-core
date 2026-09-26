"""Hard WAL bound: automatic maintenance and honest admission stops."""

import asyncio
import sqlite3

import pytest

from nexus_connector_core import CoreError, EventCursor, RuntimeEvent
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


def _limits(**overrides) -> JournalLimits:
    values = {"max_wal_bytes": 192 * 1024, "reserved_wal_bytes": 64 * 1024}
    values.update(overrides)
    return JournalLimits(**values)


def _event(text: str = "x" * 512) -> RuntimeEvent:
    """record_event allocates the sequence; the input must carry zero."""
    return RuntimeEvent("srv", "exe", "session", "epoch", 0, "text_delta",
                        "wal.test", {"text": text})


def test_wal_limits_are_validated_like_other_quotas():
    for invalid in (0, -1, True, "1", 1.5, 2**63):
        with pytest.raises(ValueError):
            JournalLimits(max_wal_bytes=invalid)
    for invalid in (-1, True, "1", 1.5, 2**63):
        with pytest.raises(ValueError):
            JournalLimits(reserved_wal_bytes=invalid)
    with pytest.raises(ValueError, match="quota/reserve"):
        JournalLimits(max_wal_bytes=1024, reserved_wal_bytes=1024)
    with pytest.raises(ValueError, match="quota/reserve"):
        JournalLimits(reserved_wal_bytes=-1)
    # Zero reserve is a legal (if aggressive) configuration.
    JournalLimits(reserved_wal_bytes=0)


def test_pinned_reader_makes_wal_ceiling_stop_admissions_honestly(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db", limits=_limits())
        try:
            for _ in range(7):
                await journal.record_event(_event())
            # Start from a small WAL so the pinned-reader growth this test
            # exercises comes only from the writes under the pin.
            await journal.checkpoint_wal()
            reader = sqlite3.connect(tmp_path / "journal.db")
            try:
                reader.execute("BEGIN")
                reader.execute("SELECT COUNT(*) FROM events").fetchone()
                blocked = False
                writes = 0
                while writes < 4000:
                    try:
                        await journal.record_event(_event())
                    except CoreError as exc:
                        assert exc.code == "JOURNAL_FULL"
                        blocked = True
                        break
                    writes += 1
                assert blocked, "pinned reader must eventually stop admissions"
                status = await journal.storage_status()
                assert status.wal_bytes + status.page_size * 4 > (
                    _limits().max_wal_bytes -
                    _limits().reserved_wal_bytes), (
                    "admission stop happened before the WAL ceiling")
                # Releasing the reader lets the next write maintain itself:
                # the bounded truncate checkpoint now succeeds and the event
                # is admitted without any host intervention.
                reader.rollback()
                reader.close()
                await journal.record_event(_event())
                recovered = await journal.storage_status()
                assert recovered.wal_bytes < status.wal_bytes
            finally:
                try:
                    reader.close()
                except sqlite3.Error:
                    pass
        finally:
            journal.close()

    asyncio.run(run())


def test_unpinned_wal_stays_bounded_by_automatic_maintenance(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db", limits=_limits())
        try:
            for _ in range(899):
                await journal.record_event(_event())
            status = await journal.storage_status()
            assert status.wal_bytes <= _limits().max_wal_bytes
            cursor = EventCursor("srv", "exe", "session", "epoch")
            sequences = tuple([item.sequence async for item in
                               journal.events(cursor)])
            assert sequences[-1] == 899
        finally:
            journal.close()

    asyncio.run(run())


def _critical() -> RuntimeEvent:
    return RuntimeEvent("srv", "exe", "session", "epoch", 0, "lifecycle",
                        "wal.critical", {"text": "y" * 512})


def test_critical_writes_use_the_wal_reserve_but_not_beyond_the_hard_cap(
        tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db", limits=_limits())
        try:
            await journal.checkpoint_wal()
            reader = sqlite3.connect(tmp_path / "journal.db")
            reader.execute("BEGIN")
            reader.execute("SELECT COUNT(*) FROM events").fetchone()
            try:
                blocked_normal = False
                writes = 0
                while writes < 4000:
                    try:
                        await journal.record_event(_event())
                    except CoreError as exc:
                        assert exc.code == "JOURNAL_FULL"
                        blocked_normal = True
                        break
                    writes += 1
                assert blocked_normal
                ceiling = _limits().max_wal_bytes - _limits(
                ).reserved_wal_bytes
                status = await journal.storage_status()
                assert status.wal_bytes + status.page_size * 4 > ceiling
                # A critical event may still be admitted while WAL headroom
                # remains inside the reserve...
                admitted = 0
                hard_blocked = False
                while admitted < 4000:
                    try:
                        await journal.record_event(_critical())
                    except CoreError as exc:
                        assert exc.code == "JOURNAL_FULL"
                        hard_blocked = True
                        break
                    admitted += 1
                # ...and must also stop at the hard cap with the reader
                # still pinning the WAL.
                assert hard_blocked and admitted > 0
                final = await journal.storage_status()
                assert final.wal_bytes <= _limits().max_wal_bytes + (
                    final.page_size * 4)
            finally:
                reader.rollback()
                reader.close()
        finally:
            journal.close()

    asyncio.run(run())
