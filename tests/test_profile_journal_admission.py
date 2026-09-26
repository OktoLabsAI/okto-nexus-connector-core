import asyncio

from nexus_connector_core.journal import JournalLimits
from tools.profile_journal_admission import run


def test_small_journal_profile_exercises_reserve_and_reopen(tmp_path):
    limits = JournalLimits(max_operation_rows=4, reserved_operation_rows=1)
    result = asyncio.run(run(tmp_path / "journal.db", normal_rows=3,
                             critical_rows=1, limits=limits))
    assert result["operations"] == 4
    assert result["database_bytes"] > 0
    assert result["normal_seconds"] >= 0
