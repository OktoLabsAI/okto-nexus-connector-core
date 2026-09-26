"""Authorized real Codex concurrent-control campaign (TK-22 shape).

One app-server connector multiplexing two threads: concurrent turns, a
steer with the live expected turn ID, a stale-ID steer refusal proven
before any write, an interrupt, and per-thread terminal correlation.
Logs only protocol metadata — never prompt output, model text or secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from nexus_connector_core.native.adapter_types import (
    HarnessCommand, RuntimeCommandNotSent,
)
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codex_exe", type=Path)
    parser.add_argument("codex_home", type=Path)
    args = parser.parse_args()
    codex_exe = args.codex_exe.resolve(strict=True)
    codex_home = args.codex_home.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="nexus-core-codex-concurrent-") as directory:
        workdir = Path(directory)
        environment = {"CODEX_HOME": str(codex_home)}
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATH",
                     "SYSTEMROOT", "TEMP", "TMP"):
            if name in os.environ:
                environment[name] = os.environ[name]
        connector = CodexAppServerConnector(
            command=(str(codex_exe), "app-server"),
            cwd=str(workdir), env=environment, handshake_timeout_s=60)
        lock = threading.Lock()
        by_session: dict[str, list[str]] = {}
        turn_ids: dict[str, str] = {}
        completed: dict[str, object] = {}
        turn_completed_events = {name: threading.Event() for name in ("a", "b")}
        approval_shapes: list[str] = []

        def consume() -> None:
            for event in connector.events():
                name = "a" if event.session_id == session_a.session_id else "b"
                with lock:
                    by_session.setdefault(name, []).append(event.native_event)
                    if len(by_session[name]) > 400:
                        by_session[name].pop(0)
                if event.native_event == "turn/started" and event.turn_id:
                    with lock:
                        turn_ids[name] = event.turn_id
                elif event.native_event == "turn/completed":
                    turn_payload = event.payload.get("turn")
                    with lock:
                        completed[name] = (turn_payload.get("status")
                                           if isinstance(turn_payload, dict)
                                           else None)
                    turn_completed_events[name].set()
                if event.payload.get("native_approval"):
                    with lock:
                        approval_shapes.append(event.native_event)

        report: dict[str, object] = {}
        try:
            session_a = connector.start(owning_agent_id="core-concurrent-a")
            session_b = connector.start(owning_agent_id="core-concurrent-b")
            report["two_threads_started"] = True
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()

            started_barrier = threading.Barrier(3)
            send_errors: list[str] = []

            def send_turn(name: str, session, text: str) -> None:
                started_barrier.wait()
                try:
                    connector.send(session, HarnessCommand(
                        session.session_id, "send_turn", {"text": text},
                        operation_id=f"turn-{name}"))
                except Exception as exc:  # noqa: BLE001 - recorded, not raised
                    with lock:
                        send_errors.append(f"{name}: {type(exc).__name__}")

            thread_a = threading.Thread(target=send_turn, args=(
                "a", session_a, "Count slowly from 1 to 40, one per line."))
            thread_b = threading.Thread(target=send_turn, args=(
                "b", session_b, "Reply with exactly: OK-B"))
            thread_a.start(); thread_b.start(); started_barrier.wait()
            thread_a.join(); thread_b.join()
            report["concurrent_sends_accepted"] = not send_errors
            report["send_errors"] = send_errors

            # Wait for both native turns to be live, then steer A with its
            # exact expected turn ID and refuse a stale ID before any write.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and len(turn_ids) < 2:
                time.sleep(0.02)
            with lock:
                target = turn_ids.get("a")
            report["both_native_turn_ids_observed"] = target is not None
            connector.send(session_a, HarnessCommand(
                session_a.session_id, "steer",
                {"text": "Stop counting. Reply with exactly: STEERED-A"},
                operation_id="steer-a", expected_turn_id=target))
            report["steer_with_expected_turn_sent"] = target is not None
            stale_refused = False
            try:
                connector.send(session_a, HarnessCommand(
                    session_a.session_id, "steer", {"text": "nope"},
                    operation_id="steer-stale",
                    expected_turn_id="00000000-0000-0000-0000-000000000000"))
            except RuntimeCommandNotSent:
                stale_refused = True
            report["stale_id_steer_refused_before_write"] = stale_refused

            connector.send(session_b, HarnessCommand(
                session_b.session_id, "interrupt", {},
                operation_id="interrupt-b", expected_turn_id=turn_ids.get("b")))
            report["interrupt_sent"] = True

            a_done = turn_completed_events["a"].wait(timeout=240)
            b_done = turn_completed_events["b"].wait(timeout=120)
            report["turn_a_completed"] = a_done
            report["turn_b_completed"] = b_done
            with lock:
                report["turn_a_status"] = completed.get("a")
                report["turn_b_status"] = completed.get("b")
                report["turn_a_methods_tail"] = by_session["a"][-12:]
                report["turn_b_methods_tail"] = by_session["b"][-12:]
                report["native_approval_shapes"] = approval_shapes
            close_begin = time.monotonic()
            connector.close()
            report["close_seconds"] = round(time.monotonic() - close_begin, 3)
            print(json.dumps(report, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
