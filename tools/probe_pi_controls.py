"""Authorized real Pi 0.87.1 control campaign: steer, abort, follow-up, shutdown.

Reads the named Pi config for existing provider authentication. Session files
go to a temporary directory. Tools, extensions, skills, templates, themes and
context files stay disabled and automatic retries are disabled before any
prompt. Logs only protocol metadata (event types, ordering, timings); never
prompt output, response text, stderr or credentials.
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
from nexus_connector_core.native.adapters.pi import PiRpcConnector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("node", type=Path)
    parser.add_argument("cli", type=Path)
    parser.add_argument("config_dir", type=Path)
    args = parser.parse_args()
    node = args.node.resolve(strict=True)
    cli = args.cli.resolve(strict=True)
    config = args.config_dir.resolve(strict=True)
    if (not node.is_file() or not cli.is_file() or cli.suffix != ".js" or
            not config.is_dir()):
        raise SystemExit("invalid explicit Pi probe paths")
    with tempfile.TemporaryDirectory(prefix="nexus-core-pi-real-controls-") as directory:
        sessions = Path(directory) / "sessions"
        sessions.mkdir()
        environment = {"PI_CODING_AGENT_DIR": str(config)}
        for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
            if name in os.environ:
                environment[name] = os.environ[name]
        connector = PiRpcConnector(
            command=(str(node), str(cli), "--mode", "rpc", "--session-dir",
                     str(sessions), "--no-tools", "--no-extensions",
                     "--no-skills", "--no-prompt-templates", "--no-themes",
                     "--no-context-files", "--no-approve"),
            version_command=(str(node), str(cli), "--version"),
            cwd=str(Path.cwd().resolve()), env=environment,
            handshake_timeout_s=15, command_timeout_s=20,
        )
        lock = threading.Lock()
        events: list[str] = []
        settled = threading.Event()
        started = threading.Event()
        queued = threading.Event()
        last_stop_reason = None
        settle_time = {}

        def consume() -> None:
            nonlocal last_stop_reason
            for event in connector.events():
                with lock:
                    if len(events) < 400:
                        events.append(event.native_event)
                if event.native_event == "agent_start":
                    started.set()
                elif event.native_event == "queue_update":
                    steering = event.payload.get("steering")
                    if isinstance(steering, list) and steering:
                        queued.set()
                elif event.native_event == "message_end":
                    message = event.payload.get("message", event.payload)
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        last_stop_reason = message.get("stopReason")
                elif event.native_event == "agent_settled":
                    settle_time["agent_settled"] = time.monotonic()
                    settled.set()

        def wait(flag: threading.Event, timeout: float, label: str) -> bool:
            if not flag.wait(timeout=timeout):
                print(f"scenario failed waiting for {label}", flush=True)
                return False
            return True

        report: dict[str, object] = {}
        try:
            session = connector.start(owning_agent_id="core-pi-real-controls")
            report["version"] = session.compatibility_report.get("native_version")
            report["response_ids_required"] = connector._transport._response_ids_required
            retry_setting = connector._transport.request(
                "set_auto_retry", {"enabled": False}, timeout_s=5)
            if retry_setting.get("success") is not True:
                raise SystemExit("Pi did not disable automatic retries")
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()

            # -- Scenario 1: steer a live text turn (ID-less, queue semantics).
            settled.clear(); started.clear(); queued.clear()
            with lock:
                events.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Count from 1 to 25, one number per line."}))
            if not wait(started, 60, "agent_start (steer scenario)"):
                raise SystemExit(1)
            connector.send(session, HarnessCommand(
                session.session_id, "steer",
                {"text": "Stop counting. Reply with exactly: STEERED"}))
            report["steer_accepted"] = True
            report["steer_queue_update_observed"] = queued.is_set() or queued.wait(10)
            settled_after = wait(settled, 120, "agent_settled (steer scenario)")
            report["steer_turn_settled"] = settled_after
            with lock:
                report["steer_scenario_events"] = events.copy()
            report["steer_last_stop_reason"] = last_stop_reason
            # A queued steer may legally drive a follow-up turn after settle;
            # observe for a bounded window without asserting it must happen.
            time.sleep(10)
            report["steer_follow_up_started_after_settle"] = started.is_set()

            # -- Scenario 2: abort mid-turn, then a real follow-up submit.
            settled.clear(); started.clear()
            with lock:
                events.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Count from 1 to 100, one number per line."}))
            if not wait(started, 60, "agent_start (abort scenario)"):
                raise SystemExit(1)
            abort_sent = time.monotonic()
            connector.send(session, HarnessCommand(
                session.session_id, "interrupt", {}))
            report["abort_ack_returned"] = True
            report["abort_settle_before_ack"] = (
                settle_time.get("agent_settled", float("inf")) < abort_sent)
            report["abort_turn_settled"] = wait(settled, 60, "agent_settled (abort)")
            with lock:
                report["abort_scenario_events"] = events.copy()
            settled.clear()
            with lock:
                events.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Reply with exactly: OK2"}))
            report["follow_up_settled"] = wait(settled, 120, "agent_settled (follow-up)")
            report["follow_up_stop_reason"] = last_stop_reason
            with lock:
                report["follow_up_scenario_events"] = events.copy()

            # -- Scenario 3: connector close during a live turn is bounded.
            settled.clear(); started.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Count from 1 to 100, one number per line."}))
            if not wait(started, 60, "agent_start (shutdown scenario)"):
                raise SystemExit(1)
            close_begin = time.monotonic()
            connector.close()
            report["shutdown_close_seconds"] = round(time.monotonic() - close_begin, 3)
            deadline = time.monotonic() + 30
            stopped = False
            while time.monotonic() < deadline:
                lifecycle = connector.observe_lifecycle(session)
                if lifecycle.get("stop_observed") is True:
                    stopped = True
                    break
                time.sleep(0.05)
            report["shutdown_stop_observed"] = stopped
            report["shutdown_bounded"] = stopped and time.monotonic() - close_begin < 35
            print(json.dumps(report, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
