"""Two application-free consumer paths, executed against an installed wheel.

The verifier runs this source with ``python -I -c`` from a temporary working
directory. It is not imported from the Core package or a sibling checkout.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import nexus_connector_core as core_package
from nexus_connector_core import (
    CloseOperation, ExecutionContext, InstallationCandidate, LaunchIntent,
    LocalRuntimeCore, OpenOperation, OperationReceipt, RuntimeEvent,
    SessionKey, ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.conformance import verify_contract_bundle
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.event_reducer import (
    event_ack_frame, event_batch_frame, reduce_durable_event_batch,
)
from nexus_connector_core.frame_codec import decode_frame, encode_frame
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.receipt_reducer import receipt_frame, reduce_receipt


class _Native:
    native_id = "consumer-native"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.stopped = False
        self.queue: asyncio.Queue[RuntimeEvent | None] = asyncio.Queue()

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        self.sent.append((verb, operation_id))

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


class _Factory:
    def __init__(self) -> None:
        self.native = _Native()
        self.opens = 0

    async def open(self, prepared, session_id, context, *, stream_epoch):
        self.opens += 1
        return self.native


async def _embedded_host() -> None:
    with tempfile.TemporaryDirectory(prefix="core-embedded-consumer-") as directory:
        root = Path(directory)
        binary = root / "selected-codex"
        binary.write_bytes(b"synthetic selected binary")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), fingerprint(binary),
            "explicit", "selected")
        journal = SQLiteJournal(root / "journal.db")
        factory = _Factory()
        runtime = LocalRuntimeCore(
            journal, factory, candidates={"codex_app_server": candidate},
            workspace_roots={"workspace": str(root)})
        context = ExecutionContext(
            "server", "executor", "binding", "agent", "workspace",
            1, 1, 1, time.monotonic() + 60,
            frozenset({"runtime.open", "turn.submit", "runtime.close"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "workspace", "codex_app_server"), context)
            opened = await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), context)
            assert opened.stage == "SUBMITTED"
            submitted = await runtime.submit(
                TurnOperation("turn", "session", "hello"), context)
            assert submitted.stage == "SUBMITTED" and submitted.possible_effect
            assert (await runtime.submit(
                TurnOperation("turn", "session", "hello"), context)) == submitted
            assert factory.opens == 1 and factory.native.sent == [("send_turn", "turn")]
            assert (await runtime.inspect(SessionKey(
                "server", "executor", "session"))).ownership == "owned"
            await runtime.close(CloseOperation("close", "session"), context)
            assert factory.native.stopped
            report = await runtime.shutdown(ShutdownPolicy())
            assert report.session_outcomes[SessionKey(
                "server", "executor", "session")] == "already_closed"
        finally:
            journal.close()


def _remote_host(expected_manifest: str) -> None:
    report = verify_contract_bundle(expected_manifest,
                                    allow_development_partial=True)
    assert report.checked_files == 9 and report.checked_frames > 0
    receipt = OperationReceipt(
        "operation", "sha256:" + "a" * 64, "OUTCOME_UNKNOWN", True, False,
        "session", error_code="OUTCOME_UNKNOWN")
    frame = receipt_frame(receipt, server_id="server", executor_id="executor")
    assert decode_frame(encode_frame(frame)) == frame
    assert reduce_receipt(None, frame).receipt.stage == "OUTCOME_UNKNOWN"
    event = RuntimeEvent(
        "server", "executor", "session", "epoch", 1, "lifecycle",
        "native.started", {})
    projection = reduce_durable_event_batch(None, event_batch_frame([event]))
    assert event_ack_frame(projection)["sequence"] == 1


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {"embedded", "remote"}:
        raise SystemExit("usage: consumer_smoke.py embedded|remote MANIFEST_SHA WHEEL_SHA")
    if (not sys.flags.isolated or
            not Path(core_package.__file__).resolve().is_relative_to(
                Path(sys.prefix).resolve())):
        raise SystemExit("consumer must import the isolated wheel installation")
    role, manifest_sha, wheel_sha = sys.argv[1:]
    if role == "embedded":
        asyncio.run(_embedded_host())
    else:
        _remote_host(manifest_sha)
    print(json.dumps({"role": role, "wheel_sha256": wheel_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
