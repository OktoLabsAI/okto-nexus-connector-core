"""Authorized real Claude slow-consumer campaign (TK-27 shape).

One long streamed turn consumed deliberately slowly: the probe sleeps
between events while the adapter's reader drains the child continuously.
The result terminal must still be observed — no silent loss under a slow
subscriber. Logs only protocol metadata — never prompt output, model text
or secrets.
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
    parser.add_argument("--per-event-ms", type=float, default=25.0)
    args = parser.parse_args()
    claude_exe = args.claude_exe.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="nexus-core-claude-slow-") as directory:
        workdir = Path(directory)
        environment = {name: value for name, value in os.environ.items()
                       if name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                   "PATH", "SYSTEMROOT", "TEMP", "TMP")}
        connector = ClaudeCodeStreamConnector(
            binary=str(claude_exe), cwd=str(workdir), env=environment)
        lock = threading.Lock()
        counts: Counter[str] = Counter()
        order: list[str] = []
        terminal = threading.Event()
        result_subtypes: list[str] = []

        def consume() -> None:
            for event in connector.events():
                prefix = event.native_event.split(":", 1)[0]
                with lock:
                    counts[prefix] += 1
                    if len(order) < 300:
                        order.append(event.native_event)
                # The slow subscriber: bounded sleep per event while the
                # adapter's own reader thread keeps draining the child.
                time.sleep(args.per_event_ms / 1000.0)
                if event.native_event.startswith("result:"):
                    with lock:
                        result_subtypes.append(
                            event.native_event.split(":", 1)[1])
                    terminal.set()
                    return

        report: dict[str, object] = {}
        try:
            session = connector.start(owning_agent_id="core-claude-slow-probe")
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            begin = time.monotonic()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"content": "Count from 1 to 150, one number per line, "
                            "then write DONE."},
                operation_id="slow-turn"))
            completed = terminal.wait(timeout=300)
            elapsed = time.monotonic() - begin
            report["result_terminal_observed"] = completed
            report["elapsed_seconds"] = round(elapsed, 1)
            report["slow_consumer_ms_per_event"] = args.per_event_ms
            with lock:
                report["event_counts"] = dict(counts)
                report["stream_events"] = counts["stream_event"]
                report["result_subtypes"] = result_subtypes.copy()
                # The terminal must be the last observed native event.
                report["terminal_was_last"] = bool(order) and (
                    order[-1].startswith("result:"))
            close_begin = time.monotonic()
            connector.close()
            report["close_seconds"] = round(time.monotonic() - close_begin, 3)
            print(json.dumps(report, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
