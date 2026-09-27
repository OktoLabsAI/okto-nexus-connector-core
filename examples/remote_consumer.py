"""Remote consumer shape: same public composition, executor-scoped context.

The Core contains no remote transport: the Connector application owns
WSS/daemon. This example demonstrates that the identical public factory
and artifact serve the remote host's executor namespace - nothing private
is imported and no application dependency exists.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from nexus_connector_core import (
    ExecutionContext, InstallationCandidate, LaunchIntent,
    OpenOperation, SessionKey, ShutdownPolicy, create_runtime,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal


class RemoteNative:
    native_id = "remote-native"

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    async def send(self, verb, payload, operation_id, *,
                   expected_turn_id=None):
        pass

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED", "IDLE")


class RemoteFactory:
    def __init__(self):
        self.native = RemoteNative()

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


async def main() -> int:
    with tempfile.TemporaryDirectory(prefix="core-remote-example-") as directory:
        root = Path(directory)
        binary = root / "selected-pi-cli.js"
        binary.write_bytes(b"synthetic selected pi cli")
        candidate = InstallationCandidate(
            "pi_rpc", str(binary), fingerprint(binary), "explicit",
            "selected")
        journal = SQLiteJournal(root / "remote-journal.db")
        runtime = create_runtime(
            journal=journal,
            environment=lambda prepared: {},
            candidates={"pi_rpc": candidate},
            workspace_roots={"workspace": str(root)},
            native_factory=RemoteFactory())
        # The remote host's executor namespace: distinct from the Server's.
        context = ExecutionContext(
            "server", "remote-executor", "remote-binding", "agent",
            "workspace", 1, 1, 1, time.monotonic() + 60,
            frozenset({"runtime.open"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "workspace", "pi_rpc"), context)
            opened = await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), context)
            assert opened.stage == "SUBMITTED"
            lease = await runtime.persisted_lease(SessionKey(
                "server", "remote-executor", "session"))
            assert lease is not None and not lease.revoked
            await runtime.shutdown(ShutdownPolicy())
            print("remote consumer: OK")
            return 0
        finally:
            journal.close()
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
