"""Reproducible synthetic 100k-row SQLite admission campaign.

This is a local journal scalability probe, not provider or multi-host
qualification. It uses only temporary storage and never replays an effect.
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

from nexus_connector_core import CoreError, OperationKey
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


async def run(path: Path, *, normal_rows: int = 99_000,
              critical_rows: int = 1000,
              limits: JournalLimits | None = None) -> dict[str, object]:
    selected_limits = limits or JournalLimits()
    if (normal_rows != selected_limits.max_operation_rows -
            selected_limits.reserved_operation_rows or
            critical_rows != selected_limits.reserved_operation_rows):
        raise ValueError("probe rows must fill the configured global budget")
    expected_rows = normal_rows + critical_rows
    journal = SQLiteJournal(path, limits=selected_limits)
    started = time.perf_counter()
    batches: list[float] = []
    batch_started = started
    try:
        for index in range(normal_rows):
            server = f"server-{index % 3}"
            session = f"session-{index % 30}"
            _, fresh = await journal.admit(
                OperationKey(server, "executor", f"normal-{index}"),
                f"intent-{index}", session)
            if not fresh:
                raise AssertionError("fresh synthetic operation was duplicate")
            if (index + 1) % 10_000 == 0:
                now = time.perf_counter()
                batches.append(now - batch_started)
                batch_started = now
        normal_seconds = time.perf_counter() - started
        try:
            await journal.admit(OperationKey("server-0", "executor", "denied"),
                                "denied", "session-0")
        except CoreError as exc:
            if exc.code != "JOURNAL_FULL" or not exc.retry_safe or exc.possible_effect:
                raise AssertionError("normal quota denial was not safe") from exc
        else:
            raise AssertionError("normal reserve was not enforced")
        for index in range(critical_rows):
            _, fresh = await journal.admit(
                OperationKey(f"server-{index % 3}", "executor",
                             f"critical-{index}"),
                f"critical-intent-{index}", f"session-{index % 30}",
                critical=True)
            if not fresh:
                raise AssertionError("critical synthetic operation was duplicate")
        try:
            await journal.admit(OperationKey("server-0", "executor", "critical-denied"),
                                "denied", "session-0", critical=True)
        except CoreError as exc:
            if exc.code != "JOURNAL_FULL":
                raise
        else:
            raise AssertionError("critical global cap was not enforced")
        duplicate, fresh = await journal.admit(
            OperationKey("server-0", "executor", "normal-0"),
            "intent-0", "session-0")
        if fresh or duplicate.operation_id != "normal-0":
            raise AssertionError("duplicate not available at saturation")
        count = journal._run_sync(lambda db: db.execute(
            "SELECT operation_rows FROM operation_usage").fetchone())[0]
        if count != expected_rows:
            raise AssertionError(f"global counter drifted: {count}")
        status = await journal.storage_status()
        elapsed = time.perf_counter() - started
    finally:
        journal.close()
    reopened_at = time.perf_counter()
    journal = SQLiteJournal(path, limits=selected_limits)
    try:
        reopened_count = journal._run_sync(lambda db: db.execute(
            "SELECT operation_rows FROM operation_usage").fetchone())[0]
        if reopened_count != expected_rows:
            raise AssertionError(f"reopen counter drifted: {reopened_count}")
        replay, fresh = await journal.admit(
            OperationKey("server-0", "executor", "normal-0"),
            "intent-0", "session-0")
        if fresh or replay.operation_id != "normal-0":
            raise AssertionError("duplicate did not survive reopen")
    finally:
        journal.close()
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "journal_module": sys.modules["nexus_connector_core.journal"].__file__,
        "operations": expected_rows,
        "normal_seconds": round(normal_seconds, 3),
        "total_seconds": round(elapsed, 3),
        "reopen_seconds": round(time.perf_counter() - reopened_at, 3),
        "normal_batch_seconds": [round(value, 3) for value in batches],
        "database_bytes": status.database_bytes,
        "wal_bytes": status.wal_bytes,
        "shm_bytes": status.shm_bytes,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nexus-core-100k-") as directory:
        print(json.dumps(asyncio.run(run(Path(directory) / "journal.db")),
                         sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
