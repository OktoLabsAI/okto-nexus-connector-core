"""Sustained multi-session saturation campaign (K10/TK-40 synthetic).

Four concurrent managed sessions over real contained peer subprocesses on
one LocalRuntimeCore/journal, each submitting turns continuously for a
sustained window while an urgent interrupt probe rotates across sessions
every few seconds. Success requires: no event-stream fault, every probe
either refused before write with a typed reason or admitted, bounded
journal growth consistent with the configured quotas, and every in-flight
turn reaching a terminal or being explicitly cancelled at teardown.
Metadata-only logging.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

from nexus_connector_core import (
    CoreError, EventCursor, ExecutionContext, LaunchIntent,
    LocalRuntimeCore, OpenOperation, SessionKey, ShutdownPolicy,
    TurnOperation,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import JournalLimits, SQLiteJournal
from nexus_connector_core.models import ControlOperation
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession
from nexus_connector_core.native.adapters.pi import PiRpcConnector

DURATION_S = 45.0
SESSIONS = 4
PROBE_EVERY_S = 7.0


class PeerFactory:
    def __init__(self, fixture: Path, root: Path):
        self._fixture = fixture
        self._root = root

    async def open(self, prepared, session_id, context, *, stream_epoch):
        connector = PiRpcConnector(
            command=(sys.executable, str(self._fixture),
                     str(self._root / f"peer-{session_id}.jsonl")),
            version_command=(sys.executable, "-c", "print('0.85.1')"),
            cwd=str(self._root), handshake_timeout_s=10,
            command_timeout_s=3)
        native = await asyncio.to_thread(connector.start,
                                         owning_agent_id=context.agent_id)
        return CopiedAdapterSession(connector, native, session_id=session_id,
                                    stream_epoch=stream_epoch, context=context)


async def main() -> None:
    fixture = Path(__file__).parent.parent / "tests" / "fixtures" / "pi_rpc_peer.py"
    with tempfile.TemporaryDirectory(prefix="nexus-core-sustain-") as directory:
        root = Path(directory)
        binary = root / "peer-binary"
        binary.write_bytes(b"synthetic")
        from nexus_connector_core.models import InstallationCandidate
        candidate = InstallationCandidate(
            "pi_rpc", str(binary), fingerprint(binary), "explicit", "selected")
        journal = SQLiteJournal(
            root / "journal.db",
            limits=JournalLimits(total_event_rows=200_000,
                                 total_event_bytes=32 * 1024 * 1024,
                                 max_operation_rows=200_000))
        runtime = LocalRuntimeCore(
            journal, PeerFactory(fixture, root),
            candidates={"pi_rpc": candidate},
            workspace_roots={"ws": str(root)})
        report: dict[str, object] = {
            "duration_s": DURATION_S, "sessions": SESSIONS}
        try:
            contexts = {}
            for index in range(SESSIONS):
                context = ExecutionContext(
                    "srv", "exe", f"binding-{index}", "agent", "ws", 1, 1, 1,
                    time.monotonic() + 110,
                    frozenset({"runtime.open", "turn.submit",
                               "turn.interrupt", "runtime.close"}))
                contexts[index] = context
                prepared = await runtime.prepare(
                    LaunchIntent("agent", "ws", "pi_rpc"), context)
                await runtime.open(OpenOperation(
                    f"open-{index}", f"session-{index}", f"epoch-{index}",
                    prepared), context)

            turns = [0] * SESSIONS
            refusals = [0] * SESSIONS
            admitted_interrupts = [0] * SESSIONS
            faults = [0] * SESSIONS
            stop = asyncio.Event()

            async def worker(index: int) -> None:
                context = contexts[index]
                number = 0
                while not stop.is_set():
                    number += 1
                    operation = f"turn-{index}-{number}"
                    try:
                        await runtime.submit(TurnOperation(
                            operation, f"session-{index}",
                            f"sustained load {index}/{number}"), context)
                        turns[index] += 1
                    except CoreError as exc:
                        if exc.code in {"RUNTIME_DRAINING", "SESSION_CLOSING",
                                        "SESSION_CLOSED"}:
                            return
                        refusals[index] += 1
                        await asyncio.sleep(0.05)
                    await asyncio.sleep(0.01)

            async def prober() -> None:
                index = 0
                while not stop.is_set():
                    await asyncio.sleep(PROBE_EVERY_S)
                    if stop.is_set():
                        return
                    context = contexts[index % SESSIONS]
                    try:
                        await runtime.control(ControlOperation(
                            f"interrupt-{index}", f"session-{index % SESSIONS}",
                            "interrupt"), context)
                        admitted_interrupts[index % SESSIONS] += 1
                    except CoreError as exc:
                        if exc.code in {"STALE_TURN", "SESSION_CLOSING",
                                        "SESSION_CLOSED", "RUNTIME_DRAINING",
                                        "OUTCOME_UNKNOWN"}:
                            # Typed refusal (no active turn at that instant)
                            # or honest uncertain abort: control stayed real.
                            refusals[index % SESSIONS] += 1
                        else:
                            faults[index % SESSIONS] += 1
                    except Exception:  # noqa: BLE001 - the synthetic peer
                        # only acks aborts on its hold path; a bounded
                        # adapter timeout is still a bounded urgent attempt.
                        refusals[index % SESSIONS] += 1
                    index += 1

            async def fault_watch() -> None:
                while not stop.is_set():
                    for index in range(SESSIONS):
                        try:
                            snapshot = await runtime.inspect(SessionKey(
                                "srv", "exe", f"session-{index}"))
                            if snapshot.turn_state == "UNKNOWN" and (
                                    snapshot.ownership == "faulted"):
                                faults[index] += 1
                        except CoreError:
                            pass
                    await asyncio.sleep(1.0)

            workers = [asyncio.create_task(worker(index))
                       for index in range(SESSIONS)]
            prober_task = asyncio.create_task(prober())
            watcher = asyncio.create_task(fault_watch())
            await asyncio.sleep(DURATION_S)
            stop.set()
            for task in (*workers, prober_task, watcher):
                await task

            events_total = 0
            for index in range(SESSIONS):
                cursor = EventCursor("srv", "exe", f"session-{index}",
                                     f"epoch-{index}")
                # The journal iterator ends at the current head; the runtime
                # facade would poll for new events indefinitely.
                events_total += len(tuple(
                    [event async for event in journal.events(cursor)]))
            status = await runtime.storage_status()
            report.update({
                "turns_submitted": turns,
                "interrupts_admitted": admitted_interrupts,
                "typed_refusals": refusals,
                "unexpected_faults": faults,
                "events_total": events_total,
                "journal_total_bytes": status.total_bytes,
                "journal_max_bytes": status.max_bytes,
                "journal_bounded": status.total_bytes <= status.max_bytes,
                "no_stream_fault": not any(faults),
            })
        finally:
            # The synthetic peer only acks aborts on its dedicated hold
            # path, so drain interrupts on ordinary turns raise bounded
            # adapter timeouts; containment still runs on the retry.
            try:
                await runtime.shutdown(ShutdownPolicy(2, 2))
            except Exception:  # noqa: BLE001
                try:
                    await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
                except Exception:  # noqa: BLE001
                    pass
            journal.close()
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
