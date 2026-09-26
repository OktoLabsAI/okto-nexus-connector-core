"""Independent SQLiteJournal writer for process-level fairness tests."""

from __future__ import annotations

import asyncio
import json
import sys

from nexus_connector_core import CoreError, OperationKey
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


async def run() -> None:
    path, server, session, prefix, limits_json, attempts, critical = sys.argv[1:]
    journal = SQLiteJournal(path, limits=JournalLimits(**json.loads(limits_json)))
    # Parent launches every writer before releasing any of them.
    if sys.stdin.buffer.read(1) != b"x":
        raise RuntimeError("start signal missing")
    admitted = []
    denied = 0
    try:
        for index in range(int(attempts)):
            operation_id = f"{prefix}-{index}"
            try:
                _, fresh = await journal.admit(
                    OperationKey(server, "executor", operation_id),
                    f"intent-{operation_id}", session,
                    critical=critical == "critical")
            except CoreError as exc:
                if (exc.code != "JOURNAL_FULL" or not exc.retry_safe or
                        exc.possible_effect):
                    raise
                denied += 1
            else:
                if not fresh:
                    raise AssertionError("unique operation was a duplicate")
                admitted.append(operation_id)
    finally:
        journal.close()
    print(json.dumps({"server": server, "session": session,
                      "admitted": admitted, "denied": denied}), flush=True)


if __name__ == "__main__":
    asyncio.run(run())
