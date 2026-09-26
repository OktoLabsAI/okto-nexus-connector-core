"""Child process that exits without SQLiteJournal.close at a named boundary."""

from __future__ import annotations

import asyncio
import os
import sys

from nexus_connector_core import (EventCursor, OperationKey, OperationReceipt,
                                  ProcessBirthEvidence, RuntimeEvent)
from nexus_connector_core.journal import SQLiteJournal


INTENT = "sha256:" + "1" * 64
KEY = OperationKey("crash-server", "crash-executor", "crash-operation")
CURSOR = EventCursor("crash-server", "crash-executor", "crash-session", "crash-epoch")


async def run(path: str, boundary: str) -> None:
    journal = SQLiteJournal(path)
    if boundary == "before_admit":
        return
    if boundary == "uncommitted_admit":
        # Deliberate fault injection inside an open SQLite transaction, not a
        # production Journal-port operation. Abrupt exit must roll it back.
        journal._db.execute("BEGIN IMMEDIATE")
        journal._db.execute(
            "INSERT INTO operations_v2 VALUES (?,?,?,?,?,?,?,?,?,?)",
            (KEY.server_id, KEY.executor_id, KEY.operation_id, INTENT,
             CURSOR.session_id, "RECEIVED_DURABLE", 0, 1, None, None))
        return
    if boundary == "after_ack":
        event = RuntimeEvent(CURSOR.server_id, CURSOR.executor_id,
                             CURSOR.session_id, CURSOR.stream_epoch, 1,
                             "lifecycle", "crash.started", {})
        await journal.append_event(event)
        await journal.acknowledge_events(CURSOR, 1)
        return
    await journal.admit(
        KEY, INTENT, CURSOR.session_id,
        effect_imminent=boundary not in {"after_admit", "after_mark"},
        claim_session=boundary in {"before_birth", "uncommitted_birth",
                                   "after_birth"},
        connection_generation=(3 if boundary in {"before_birth",
                                                 "uncommitted_birth",
                                                 "after_birth"} else None),
        session_owner_generation=(1 if boundary in {"before_birth",
                                                   "uncommitted_birth",
                                                   "after_birth"} else None))
    if boundary in {"before_birth", "uncommitted_birth", "after_birth"}:
        if boundary == "before_birth":
            return
        birth = ProcessBirthEvidence("linux", 45678,
                                     "boot-start:crash-boot:123",
                                     "linux_guardian")
        if boundary == "uncommitted_birth":
            # Fault between the INSERT and COMMIT of the birth fact.
            journal._db.execute("BEGIN IMMEDIATE")
            journal._db.execute(
                "INSERT INTO process_births VALUES (?,?,?,?,?,?,?,?)",
                (KEY.server_id, KEY.executor_id, CURSOR.session_id,
                 KEY.operation_id, birth.platform, birth.pid,
                 birth.birth_token, birth.containment))
            return
        await journal.record_process_birth(KEY, CURSOR.session_id, birth)
        return
    if boundary == "after_admit":
        return
    if boundary == "after_mark":
        await journal.mark_possible_effect(KEY)
    elif boundary == "after_no_write":
        await journal.record_not_sent(KEY, "SAFE_NO_WRITE")
    elif boundary == "after_unknown":
        await journal.record_receipt(KEY, OperationReceipt(
            KEY.operation_id, INTENT, "OUTCOME_UNKNOWN", True, False,
            CURSOR.session_id))
    elif boundary == "after_terminal":
        await journal.append_event(RuntimeEvent(
            CURSOR.server_id, CURSOR.executor_id, CURSOR.session_id,
            CURSOR.stream_epoch, 1, "turn_state", "crash.terminal",
            {"delivery_phase": "terminal", "delivery_outcome": "success"},
            KEY.operation_id))
    else:
        raise ValueError(boundary)


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2]))
    os._exit(91)
