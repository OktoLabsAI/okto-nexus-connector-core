"""One authorized real Pi turn, without tools, logging only protocol metadata.

Reads the named Pi config for existing provider authentication. Session files
go to a temporary directory. Does not print prompt output, stderr or secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
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
    with tempfile.TemporaryDirectory(prefix="nexus-core-pi-real-turn-") as directory:
        sessions = Path(directory) / "sessions"
        sessions.mkdir()
        environment = {"PI_CODING_AGENT_DIR": str(config)}
        for name in ("APPDATA", "LOCALAPPDATA"):
            if name in os.environ:
                environment[name] = os.environ[name]
        connector = PiRpcConnector(
            command=(str(node), str(cli), "--mode", "rpc", "--session-dir",
                     str(sessions), "--no-tools", "--no-extensions",
                     "--no-skills", "--no-prompt-templates", "--no-themes",
                     "--no-context-files", "--no-approve"),
            version_command=(str(node), str(cli), "--version"),
            cwd=str(Path.cwd().resolve()), env=environment,
            handshake_timeout_s=10, command_timeout_s=10,
        )
        seen = []
        done = threading.Event()
        stop_reason = None

        def consume() -> None:
            nonlocal stop_reason
            for event in connector.events():
                if len(seen) < 64:
                    seen.append(event.native_event)
                if event.native_event == "message_end":
                    message = event.payload.get("message", event.payload)
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        stop_reason = message.get("stopReason")
                if event.native_event == "agent_settled":
                    done.set()
                    return

        try:
            session = connector.start(owning_agent_id="core-pi-real-probe")
            retry_setting = connector._transport.request(
                "set_auto_retry", {"enabled": False}, timeout_s=5)
            if retry_setting.get("success") is not True:
                raise SystemExit("Pi did not disable automatic retries")
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            connector.send(session, HarnessCommand(
                session.session_id, "send_turn",
                {"text": "Reply with exactly: OK"}, operation_id="real-probe-1"))
            settled = done.wait(timeout=90)
            print(json.dumps({
                "version": session.compatibility_report.get("native_version"),
                "response_ids_required": connector._transport._response_ids_required,
                "prompt_accepted": True,
                "agent_start_observed": "agent_start" in seen,
                "agent_settled_observed": settled,
                "assistant_stop_reason": stop_reason,
                "event_types": seen,
                "tools_enabled": False,
                "session_dir_disposable": True,
            }, sort_keys=True))
            if not settled:
                raise SystemExit("Pi real turn did not settle within 90 seconds")
        finally:
            connector.close()


if __name__ == "__main__":
    main()
