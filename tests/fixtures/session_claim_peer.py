"""Independent process contender for one durable session claim."""

from __future__ import annotations

import asyncio
import json
import sys

from nexus_connector_core import CoreError, OperationKey
from nexus_connector_core.journal import SQLiteJournal


async def run() -> None:
    path, operation_id = sys.argv[1:]
    journal = SQLiteJournal(path)
    if sys.stdin.buffer.read(1) != b"x":
        raise RuntimeError("start signal missing")
    try:
        try:
            generation = 5 if operation_id == "open-a" else 6
            _, fresh = await journal.admit(
                OperationKey("srv", "exe", operation_id),
                f"intent-{operation_id}", "session", claim_session=True,
                connection_generation=generation,
                session_owner_generation=generation + 2)
        except CoreError as exc:
            if exc.code != "SESSION_CONFLICT":
                raise
            result = "conflict"
        else:
            if not fresh:
                raise AssertionError("unique open was a duplicate")
            result = "admitted"
    finally:
        journal.close()
    print(json.dumps({"operation_id": operation_id, "result": result}),
          flush=True)


if __name__ == "__main__":
    asyncio.run(run())
