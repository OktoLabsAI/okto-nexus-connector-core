"""Authorized real managed shutdown-during-active-turn campaign (K04).

Opens each adapter through the production factory, submits a long real
turn, then calls `runtime.shutdown` while the turn is still running. The
report must be finite and honest (graceful/forced/unknown per session),
bounded in wall time, with no live process left behind. Logs only protocol
metadata — never prompt output, model text or secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from nexus_connector_core import (
    CoreError, ExecutionContext, LaunchIntent, LocalRuntimeCore,
    OpenOperation, SessionKey, ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.discovery import (
    candidate as discovery_candidate, candidate_pi_node_cli,
    probe_selected_claude, probe_selected_codex, probe_selected_pi,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory

_PROMPTS = {
    "codex_app_server": "Count slowly from 1 to 300, one number per line.",
    "pi_rpc": "Count slowly from 1 to 300, one number per line.",
    "claude_stream": "Count from 1 to 300, one number per line, slowly.",
}


async def _run(adapter: str, paths: dict[str, str]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(
            prefix=f"nexus-core-managed-shutdown-{adapter}-") as directory:
        root = Path(directory)
        workspace = root / "ws"
        workspace.mkdir()
        overlay: dict[str, str] = {
            name: value for name, value in os.environ.items()
            if name.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                                "PATH", "TEMP", "TMP", "LANG", "LC_ALL",
                                "TERM"}
        }
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            if name in os.environ:
                overlay[name] = os.environ[name]
        if adapter == "codex_app_server":
            candidate = await probe_selected_codex(
                discovery_candidate("codex_app_server", paths["codex"],
                                    explicit=True),
                cwd=workspace, env=overlay)
            overlay["CODEX_HOME"] = paths["codex_home"]
        elif adapter == "pi_rpc":
            candidate = await probe_selected_pi(
                candidate_pi_node_cli(paths["node"], paths["pi_cli"],
                                      explicit=True),
                cwd=workspace, env=overlay)
            overlay["PI_CODING_AGENT_DIR"] = paths["pi_config"]
        else:
            candidate = await probe_selected_claude(
                discovery_candidate("claude_stream", paths["claude"],
                                    explicit=True),
                cwd=workspace, env=overlay)

        async def environment(_prepared) -> dict[str, str]:
            return dict(overlay)

        journal = SQLiteJournal(root / "journal.db")
        runtime = LocalRuntimeCore(
            journal, CopiedAdapterFactory(environment),
            candidates={adapter: candidate},
            workspace_roots={"ws": str(workspace)})
        context = ExecutionContext(
            "srv", "exe", "binding", "agent", "ws", 1, 1, 1,
            time.monotonic() + 90,
            frozenset({"runtime.open", "turn.submit", "turn.interrupt",
                       "runtime.close"}))
        report: dict[str, object] = {}
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", adapter), context)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), context)
            submitted = await runtime.submit(
                TurnOperation("turn", "session", _PROMPTS[adapter]), context)
            report["submit_stage"] = submitted.stage
            # Give the provider a moment to actually start the turn, then
            # shut down while it is demonstrably in flight.
            await asyncio.sleep(4)
            began = time.monotonic()
            shutdown = await runtime.shutdown(ShutdownPolicy(3, 3))
            elapsed = time.monotonic() - began
            report["shutdown_seconds"] = round(elapsed, 2)
            report["shutdown_bounded"] = elapsed < 45
            outcome = shutdown.session_outcomes.get(
                SessionKey("srv", "exe", "session"))
            report["session_outcome"] = outcome
            report["outcome_honest"] = outcome in {
                "graceful", "forced", "unknown", "already_closed"}
            # After shutdown the session must refuse new work honestly.
            try:
                await runtime.submit(
                    TurnOperation("late", "session", "nope"), context)
                report["late_submit_refused"] = False
            except CoreError as exc:
                report["late_submit_refused"] = True
                report["late_submit_code"] = exc.code
            from nexus_connector_core import OperationKey
            receipt = await journal.get_receipt(
                OperationKey("srv", "exe", "turn"))
            report["turn_receipt_stage"] = receipt.stage if receipt else None
            report["turn_receipt_possible_effect"] = (
                receipt.possible_effect if receipt else None)
        finally:
            try:
                await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            except CoreError:
                pass
            journal.close()
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adapter", choices=sorted(_PROMPTS))
    parser.add_argument("--codex", default="")
    parser.add_argument("--codex-home", default="")
    parser.add_argument("--node", default="")
    parser.add_argument("--pi-cli", default="")
    parser.add_argument("--pi-config", default="")
    parser.add_argument("--claude", default="")
    args = parser.parse_args()
    paths = {name.replace("-", "_"): getattr(args, name.replace("-", "_"))
             for name in ("codex", "codex-home", "node", "pi-cli",
                          "pi-config", "claude")}
    print(json.dumps(asyncio.run(_run(args.adapter, paths)),
                     sort_keys=True))


if __name__ == "__main__":
    main()
