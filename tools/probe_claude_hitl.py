"""Authorized real Claude HITL campaign (TK-29 shape).

Opt-in native approvals on the copied stream connector; one prompt that
must use the Bash tool. The host-side probe declines the recorded
`control_request:can_use_tool` request through the adapter's checked reply
path, observes the turn's honest terminal, and refuses a forged tool kind.
Logs only protocol metadata — never prompt output, model text or secrets.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
from pathlib import Path

from nexus_connector_core.native.adapter_types import (
    HarnessCommand, RuntimeCommandNotSent,
)
from nexus_connector_core.native.adapters.claude_code_stream import (
    ClaudeCodeStreamConnector,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claude_exe", type=Path)
    args = parser.parse_args()
    claude_exe = args.claude_exe.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="nexus-core-claude-hitl-") as directory:
        workdir = Path(directory)
        import os
        environment = {name: value for name, value in os.environ.items()
                       if name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                   "PATH", "SYSTEMROOT", "TEMP", "TMP")}
        connector = ClaudeCodeStreamConnector(
            binary=str(claude_exe), cwd=str(workdir), env=environment)
        connector.native_approvals_enabled = True
        lock = threading.Lock()
        counts: dict[str, int] = {}
        approval_request = {}
        approval_seen = threading.Event()
        terminal = threading.Event()
        result_subtypes: list[str] = []

        def consume() -> None:
            for event in connector.events():
                prefix = event.native_event.split(":", 1)[0]
                with lock:
                    counts[prefix] = counts.get(prefix, 0) + 1
                request = event.payload.get("native_approval")
                if isinstance(request, dict) and not approval_seen.is_set():
                    with lock:
                        approval_request.update(request)
                    approval_seen.set()
                if event.native_event.startswith("result:"):
                    with lock:
                        result_subtypes.append(event.native_event.split(":", 1)[1])
                    terminal.set()

        report: dict[str, object] = {}
        try:
            session = connector.start(owning_agent_id="core-claude-hitl-probe")
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"content": "Create a file named core-hitl-probe.txt in the "
                            "current directory with the content hello, using "
                            "the Write tool."},
                operation_id="hitl-turn"))
            if not approval_seen.wait(timeout=150):
                report["permission_request_observed"] = False
                report["event_counts"] = counts.copy()
                terminal.wait(timeout=60)
                print(json.dumps(report, sort_keys=True))
                return
            report["permission_request_observed"] = True
            with lock:
                request_snapshot = dict(approval_request)
            report["permission_method"] = request_snapshot.get("method")
            report["permission_tool"] = request_snapshot.get(
                "params", {}).get("tool_name")
            # A forged tool kind must be refused before any wire write.
            # Forge a DIFFERENT tool than the observed one, otherwise the
            # forgery is indistinguishable from the legitimate reply.
            observed_tool = request_snapshot.get("params", {}).get("tool_name")
            forged_tool = "Bash" if observed_tool != "Bash" else "Write"
            forged = dict(request_snapshot)
            forged["params"] = dict(request_snapshot.get("params", {}))
            forged["params"]["tool_name"] = forged_tool
            forged_refused = False
            try:
                connector.reply_native_approval(
                    session.session_id, forged, "decline")
            except RuntimeCommandNotSent:
                forged_refused = True
            report["forged_tool_kind_refused"] = forged_refused
            connector.reply_native_approval(
                session.session_id, request_snapshot, "decline")
            report["decline_delivered"] = True
            completed = terminal.wait(timeout=180)
            report["result_after_decline_observed"] = completed
            with lock:
                report["result_subtypes"] = result_subtypes.copy()
                report["event_counts"] = counts.copy()
            close_begin = time.monotonic()
            connector.close()
            report["close_seconds"] = round(time.monotonic() - close_begin, 3)
            print(json.dumps(report, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
