"""Authorized real Claude 2.1.282 stream-json turn/control campaign.

Spawns the explicitly selected native ``claude`` CLI in stream-json mode with
the user's existing home (authentication only; no credentials are read, copied
or printed). Work happens in a disposable working directory. Logs only
protocol metadata: event type prefixes, result subtypes and timings; never
prompt output, model text, stderr or secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

from nexus_connector_core.native.adapter_types import HarnessCommand
from nexus_connector_core.native.adapters.claude_code_stream import (
    ClaudeCodeStreamConnector,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claude_exe", type=Path)
    args = parser.parse_args()
    claude_exe = args.claude_exe.resolve(strict=True)
    if not claude_exe.is_file():
        raise SystemExit("invalid explicit Claude probe path")
    with tempfile.TemporaryDirectory(prefix="nexus-core-claude-real-") as directory:
        workdir = Path(directory)
        environment = {}
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            if name in os.environ:
                environment[name] = os.environ[name]
        connector = ClaudeCodeStreamConnector(
            binary=str(claude_exe), cwd=str(workdir), env=environment)
        lock = threading.Lock()
        counts: Counter[str] = Counter()
        ordered: list[str] = []
        terminal = threading.Event()
        generating = threading.Event()
        result_subtypes: list[str] = []

        def consume() -> None:
            for event in connector.events():
                prefix = event.native_event.split(":", 1)[0]
                with lock:
                    counts[prefix] += 1
                    if len(ordered) < 200 and prefix not in {
                            "stream_event", "assistant"}:
                        ordered.append(event.native_event)
                if prefix == "stream_event":
                    generating.set()
                if event.native_event.startswith("result:"):
                    with lock:
                        result_subtypes.append(event.native_event.split(":", 1)[1])
                    terminal.set()

        def wait(flag: threading.Event, timeout: float, label: str) -> bool:
            if not flag.wait(timeout=timeout):
                print(f"scenario failed waiting for {label}", flush=True)
                return False
            return True

        def snapshot() -> dict[str, object]:
            with lock:
                return {"event_counts": dict(counts), "ordered": ordered.copy(),
                        "result_subtypes": result_subtypes.copy()}

        report: dict[str, object] = {}
        try:
            session = connector.start(owning_agent_id="core-claude-real-probe")
            report["started"] = True
            report["compatibility_version"] = (
                session.compatibility_report.get("native_version"))
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()

            # -- Turn 1: plain turn; the result frame is the terminal.
            terminal.clear(); generating.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"content": "Reply with exactly: OK"}, operation_id="real-turn-1"))
            report["turn1_result_observed"] = wait(terminal, 180, "result (1)")
            report["turn1"] = snapshot()
            report["turn1_deltas_observed"] = generating.is_set()

            # -- Turn 2: second turn over the same stream-json process.
            terminal.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"content": "Reply with exactly: OK2"}, operation_id="real-turn-2"))
            report["turn2_result_observed"] = wait(terminal, 180, "result (2)")
            report["turn2"] = snapshot()

            # -- Turn 3: interrupt while the turn is generating content.
            terminal.clear(); generating.clear()
            with lock:
                result_subtypes.clear()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"content": "Count from 1 to 60, one number per line."},
                operation_id="real-turn-3"))
            if not wait(generating, 90, "stream deltas (3)"):
                raise SystemExit(1)
            connector.send(session, HarnessCommand(
                session.session_id, "interrupt", {},
                operation_id="real-interrupt-1"))
            report["interrupt_sent_while_generating"] = True
            report["interrupt_result_observed"] = wait(terminal, 120, "result (3)")
            report["turn3"] = snapshot()

            close_begin = time.monotonic()
            connector.close()
            report["close_seconds"] = round(time.monotonic() - close_begin, 3)
            deadline = time.monotonic() + 30
            stopped = False
            while time.monotonic() < deadline:
                lifecycle = connector.observe_lifecycle(session)
                if lifecycle.get("stop_observed") is True:
                    stopped = True
                    break
                time.sleep(0.05)
            report["process_stop_observed"] = stopped
            print(json.dumps(report, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
