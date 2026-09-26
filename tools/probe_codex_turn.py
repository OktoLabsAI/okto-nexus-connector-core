"""Authorized real Codex 0.157.0 turn/control campaign.

Spawns the explicitly selected native ``codex app-server`` with the user's
existing CODEX_HOME (authentication only; no credentials are read, copied or
printed). Work happens in a disposable working directory. Logs only protocol
metadata: method names, opaque thread/turn IDs, turn statuses and timings;
never prompt output, model text, stderr or secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from nexus_connector_core.native.adapter_types import HarnessCommand
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codex_exe", type=Path)
    parser.add_argument("codex_home", type=Path)
    args = parser.parse_args()
    codex_exe = args.codex_exe.resolve(strict=True)
    codex_home = args.codex_home.resolve(strict=True)
    if not codex_exe.is_file() or not codex_home.is_dir():
        raise SystemExit("invalid explicit Codex probe paths")
    with tempfile.TemporaryDirectory(prefix="nexus-core-codex-real-") as directory:
        workdir = Path(directory)
        environment = {"CODEX_HOME": str(codex_home)}
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            if name in os.environ:
                environment[name] = os.environ[name]
        connector = CodexAppServerConnector(
            command=(str(codex_exe), "app-server"),
            cwd=str(workdir), env=environment,
            handshake_timeout_s=60,
        )
        lock = threading.Lock()
        methods: list[str] = []
        turn_started = threading.Event()
        turn_completed = threading.Event()
        active_turn_id: list[str] = []
        completed_status: list[object] = []

        def consume() -> None:
            for event in connector.events():
                with lock:
                    if len(methods) < 600:
                        methods.append(event.native_event)
                if event.native_event == "turn/started":
                    if event.turn_id:
                        with lock:
                            active_turn_id.append(event.turn_id)
                    turn_started.set()
                elif event.native_event == "turn/completed":
                    turn_payload = event.payload.get("turn")
                    if isinstance(turn_payload, dict):
                        with lock:
                            completed_status.append(
                                turn_payload.get("status", turn_payload.get("reason")))
                    turn_completed.set()

        def current_turn() -> str | None:
            with lock:
                return active_turn_id[-1] if active_turn_id else None

        def wait(flag: threading.Event, timeout: float, label: str) -> bool:
            if not flag.wait(timeout=timeout):
                print(f"scenario failed waiting for {label}", flush=True)
                return False
            return True

        report: dict[str, object] = {}
        try:
            session = connector.start(owning_agent_id="core-codex-real-probe")
            report["handshake_and_thread_start"] = True
            report["compatibility_version"] = (
                session.compatibility_report.get("native_version"))
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()

            # -- Turn 1: plain turn, terminal must be the turn/completed.
            turn_started.clear(); turn_completed.clear()
            with lock:
                methods.clear(); active_turn_id.clear(); completed_status.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Reply with exactly: OK"}, operation_id="real-turn-1"))
            report["turn1_completed"] = wait(turn_completed, 180, "turn/completed (1)")
            report["turn1_id_observed"] = current_turn() is not None
            report["turn1_status"] = completed_status[-1] if completed_status else None
            with lock:
                report["turn1_methods"] = methods.copy()

            # -- Turn 2: steer with the explicit expected native turn ID.
            turn_started.clear(); turn_completed.clear()
            with lock:
                methods.clear(); active_turn_id.clear(); completed_status.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Count from 1 to 30, one number per line."},
                operation_id="real-turn-2"))
            if not wait(turn_started, 60, "turn/started (2)"):
                raise SystemExit(1)
            steer_target = current_turn()
            connector.send(session, HarnessCommand(
                session.session_id, "steer",
                {"text": "Stop counting. Reply with exactly: STEERED"},
                operation_id="real-steer-1", expected_turn_id=steer_target))
            report["steer_sent_with_expected_turn"] = steer_target
            report["steer_turn_completed"] = wait(turn_completed, 180,
                                                  "turn/completed (2)")
            report["steer_turn_status"] = completed_status[-1] if completed_status else None
            with lock:
                report["steer_methods"] = methods.copy()

            # -- Turn 3: interrupt with the explicit expected native turn ID.
            turn_started.clear(); turn_completed.clear()
            with lock:
                methods.clear(); active_turn_id.clear(); completed_status.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Count from 1 to 100, one number per line."},
                operation_id="real-turn-3"))
            if not wait(turn_started, 60, "turn/started (3)"):
                raise SystemExit(1)
            interrupt_target = current_turn()
            connector.send(session, HarnessCommand(
                session.session_id, "interrupt", {},
                operation_id="real-interrupt-1", expected_turn_id=interrupt_target))
            report["interrupt_sent_with_expected_turn"] = interrupt_target
            report["interrupt_turn_completed"] = wait(turn_completed, 120,
                                                      "turn/completed (3)")
            report["interrupt_turn_status"] = (completed_status[-1]
                                               if completed_status else None)
            with lock:
                report["interrupt_methods"] = methods.copy()

            close_begin = time.monotonic()
            connector.close()
            report["close_seconds"] = round(time.monotonic() - close_begin, 3)
            print(json.dumps(report, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
