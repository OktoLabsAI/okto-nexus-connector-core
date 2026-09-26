"""Authorized real Codex HITL campaign (TK-23 shape).

Opt-in native approvals on the copied connector; one prompt that must run a
shell command under the default on-request approval policy. The host-side
probe declines the recorded native request through the adapter's checked
reply path, then attempts the same reply again after the turn ended (the
tardy case). Logs only protocol metadata — never prompt output, model text
or secrets.
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
    with tempfile.TemporaryDirectory(prefix="nexus-core-codex-hitl-") as directory:
        workdir = Path(directory)
        environment = {"CODEX_HOME": str(codex_home)}
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATH",
                     "SYSTEMROOT", "TEMP", "TMP"):
            if name in os.environ:
                environment[name] = os.environ[name]
        connector = CodexAppServerConnector(
            command=(str(codex_exe), "app-server"),
            cwd=str(workdir), env=environment, handshake_timeout_s=60)
        connector.native_approvals_enabled = True
        lock = threading.Lock()
        methods: list[str] = []
        approval_request = {}
        approval_seen = threading.Event()
        turn_completed = threading.Event()
        turn_status = []

        def consume() -> None:
            for event in connector.events():
                with lock:
                    if len(methods) < 400:
                        methods.append(event.native_event)
                request = event.payload.get("native_approval")
                if isinstance(request, dict) and not approval_seen.is_set():
                    with lock:
                        approval_request.update(request)
                    approval_seen.set()
                if event.native_event == "turn/completed":
                    turn_payload = event.payload.get("turn")
                    with lock:
                        turn_status.append(turn_payload.get("status")
                                           if isinstance(turn_payload, dict)
                                           else None)
                    turn_completed.set()

        report: dict[str, object] = {}
        try:
            session = connector.start(owning_agent_id="core-codex-hitl-probe")
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Run this exact shell command and show me its "
                         "output: echo core-hitl-probe"},
                operation_id="hitl-turn"))
            if not approval_seen.wait(timeout=120):
                report["approval_request_observed"] = False
                report["methods"] = methods[:]
                turn_completed.wait(timeout=60)
                print(json.dumps(report, sort_keys=True))
                return
            report["approval_request_observed"] = True
            with lock:
                request_snapshot = dict(approval_request)
                method = request_snapshot.get("method")
            report["approval_method"] = method
            report["available_decisions"] = request_snapshot.get(
                "params", {}).get("availableDecisions")
            connector.reply_native_approval(
                session.session_id, request_snapshot, "decline")
            report["decline_delivered"] = True
            completed = turn_completed.wait(timeout=180)
            report["turn_completed_after_decline"] = completed
            with lock:
                report["turn_status"] = turn_status[-1] if turn_status else None
                report["methods"] = methods[:]
            # Tardy reply: the turn has ended; the same request must be
            # refused instead of being applied to anything.
            tardy_refused = False
            try:
                connector.reply_native_approval(
                    session.session_id, request_snapshot, "decline")
            except RuntimeCommandNotSent:
                tardy_refused = True
            report["tardy_reply_refused"] = tardy_refused
            close_begin = time.monotonic()
            connector.close()
            report["close_seconds"] = round(time.monotonic() - close_begin, 3)
            print(json.dumps(report, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
