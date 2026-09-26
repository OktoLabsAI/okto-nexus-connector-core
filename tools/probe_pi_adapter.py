"""No-turn smoke of the Core-owned Pi adapter with an explicit Node/Pi pair."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from nexus_connector_core.native.adapters.pi import PiRpcConnector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("node", type=Path)
    parser.add_argument("cli", type=Path)
    args = parser.parse_args()
    node = args.node.resolve(strict=True)
    cli = args.cli.resolve(strict=True)
    if not node.is_file() or not cli.is_file() or cli.suffix != ".js":
        raise SystemExit("expected explicit Node executable and Pi CLI JavaScript")
    with tempfile.TemporaryDirectory(prefix="nexus-core-pi-adapter-") as directory:
        config = Path(directory) / "config"
        sessions = Path(directory) / "sessions"
        config.mkdir()
        sessions.mkdir()
        environment = {"PI_CODING_AGENT_DIR": str(config), "PI_OFFLINE": "1"}
        for name in ("APPDATA", "LOCALAPPDATA"):
            if name in os.environ:
                environment[name] = os.environ[name]
        connector = PiRpcConnector(
            command=(str(node), str(cli), "--mode", "rpc", "--session-dir",
                     str(sessions), "--no-tools", "--no-extensions",
                     "--no-skills", "--no-prompt-templates", "--no-themes",
                     "--no-context-files", "--no-approve", "--offline"),
            cwd=str(Path.cwd().resolve()), env=environment,
            handshake_timeout_s=8, command_timeout_s=8,
        )
        try:
            session = connector.start(owning_agent_id="core-probe")
            print(json.dumps({
                "version": session.compatibility_report.get("native_version"),
                "response_ids_required": connector._transport._response_ids_required,
                "session_started": bool(session.session_id),
                "model_request_sent": False,
            }, sort_keys=True))
        finally:
            connector.close()


if __name__ == "__main__":
    main()
