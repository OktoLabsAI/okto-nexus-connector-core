"""Embedded consumer: the public composition contract, end to end.

Uses only public exports (``create_runtime`` included). The native
factory here is a contract-level fake, as the correction plan allows for
consumer smokes; production hosts omit ``native_factory`` and receive the
real copied-adapter factory without importing anything private.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from nexus_connector_core import (
    CloseOperation, ExecutionContext, EventCursor, InstallationCandidate,
    LaunchIntent, OpenOperation, RuntimeEvent, SessionKey, ShutdownPolicy,
    TurnOperation, create_runtime,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal


class ContractNative:
    native_id = "contract-native"

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.stopped = False

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        if verb == "send_turn":
            await self.queue.put(RuntimeEvent(
                "server", "executor", "session", "epoch", 0, "turn_state",
                "contract.terminal",
                {"delivery_phase": "terminal", "delivery_outcome": "success"},
                operation_id))

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


class ContractFactory:
    def __init__(self):
        self.native = ContractNative()

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


async def main() -> int:
    with tempfile.TemporaryDirectory(prefix="core-embedded-example-") as directory:
        root = Path(directory)
        binary = root / "selected-codex"
        binary.write_bytes(b"synthetic selected binary")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), fingerprint(binary),
            "explicit", "selected")
        journal = SQLiteJournal(root / "journal.db")
        runtime = create_runtime(
            journal=journal,
            environment=lambda prepared: {},
            candidates={"codex_app_server": candidate},
            workspace_roots={"workspace": str(root)},
            native_factory=ContractFactory())
        context = ExecutionContext(
            "server", "executor", "binding", "agent", "workspace",
            1, 1, 1, time.monotonic() + 60,
            frozenset({"runtime.open", "turn.submit", "runtime.close"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "workspace", "codex_app_server"),
                context)
            opened = await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), context)
            assert opened.stage == "SUBMITTED"
            submitted = await runtime.submit(
                TurnOperation("turn", "session", "hello"), context)
            assert submitted.stage in {"SUBMITTED", "SUCCEEDED"}
            async for event in runtime.events(EventCursor(
                    "server", "executor", "session", "epoch")):
                if event.payload.get("delivery_phase") == "terminal":
                    break
            await runtime.close(CloseOperation("close", "session"), context)
            report = await runtime.shutdown(ShutdownPolicy())
            assert report.session_outcomes[SessionKey(
                "server", "executor", "session")] == "already_closed"
            print("embedded consumer: OK")
            return 0
        finally:
            journal.close()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
