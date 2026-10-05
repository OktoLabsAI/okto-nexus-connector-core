"""Abruptly exit a kernel supervisor around a real owned LF child process."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from nexus_connector_core import ExecutionContext, Operation
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel
from nexus_connector_core.native.process import spawn_owned_process


def _crash_on_release(native_pid: int | None) -> None:
    print(json.dumps({"native_pid": native_pid}), flush=True)
    sys.stdin.readline()
    os._exit(91)


class FaultJournal(SQLiteJournal):
    native_pid: int | None = None
    boundary: str = ""

    async def record_receipt(self, key, receipt):
        result = await super().record_receipt(key, receipt)
        if self.boundary == "after_receipt":
            _crash_on_release(self.native_pid)
        return result


async def run(db_path: str, marker: str, boundary: str) -> None:
    journal = FaultJournal(db_path)
    journal.boundary = boundary
    kernel = OperationKernel(journal)
    operation = Operation("owned-crash-operation", "owned-session",
                          "turn.submit", {"text": "local peer"})
    context = ExecutionContext(
        "owned-server", "owned-executor", "binding", "agent", "workspace",
        1, 1, 7, time.monotonic() + 60, frozenset({"turn.submit"}))

    async def effect():
        if boundary == "before_spawn":
            _crash_on_release(None)
        native_peer = Path(__file__).with_name("owned_native_peer.py")
        process = spawn_owned_process(
            (sys.executable, str(native_peer), marker),
            cwd=str(Path(marker).parent), env=dict(os.environ))
        # Retain the owned Job/guardian until the injected supervisor crash.
        # Dropping the process object after effect() returns can close the
        # Windows kill-on-close Job before the after_receipt boundary is reached.
        journal.native_process = process
        ready = process.stdout.readline().decode("ascii").strip()
        if not ready.startswith("READY "):
            raise RuntimeError("native peer did not become ready")
        journal.native_pid = int(ready.split()[1])
        if boundary == "after_spawn":
            _crash_on_release(journal.native_pid)
        if boundary == "after_partial_write":
            process.stdin.write(b'{"cmd":"go"')
            process.stdin.flush()
            _crash_on_release(journal.native_pid)
        process.stdin.write(b'{"cmd":"go"}\n')
        process.stdin.flush()
        if process.stdout.readline().strip() != b"ACK":
            raise RuntimeError("native peer did not ACK command")
        if boundary == "after_write":
            _crash_on_release(journal.native_pid)
        return "native-id"

    await kernel.execute(operation, context, effect)


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3]))
    os._exit(91)
