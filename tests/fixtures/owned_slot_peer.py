"""Independent contender for one shared SQLite owned-process slot."""

import asyncio
import json
import os
import sys
from dataclasses import replace

from nexus_connector_core import (CoreError, OperationKey,
                                  SQLiteOwnedSlotLedger)
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


async def run(path: str, contender: str, mode: str) -> None:
    if mode == "installation":
        slots = SQLiteOwnedSlotLedger(path, max_slots=2)
    elif mode == "journal":
        slots = SQLiteJournal(path, limits=replace(JournalLimits(),
                                                  max_owned_slots=2))
    else:
        raise ValueError(mode)
    key = OperationKey("srv", "exe", f"open-{contender}")
    if mode == "journal":
        await slots.admit(key, f"intent-{contender}", f"session-{contender}",
                          claim_session=True, effect_imminent=True)
    print("ready", flush=True)
    if sys.stdin.buffer.read(1) != b"x":
        raise RuntimeError("start signal missing")
    try:
        await slots.reserve_owned_slot(key, f"session-{contender}")
    except CoreError as exc:
        result = exc.code
    else:
        result = "reserved"
    print(json.dumps({"contender": contender, "result": result}), flush=True)


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3]))
    os._exit(91)
