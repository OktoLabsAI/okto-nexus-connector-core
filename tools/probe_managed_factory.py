"""Authorized real managed-open smoke through the Core production gate.

For one adapter (codex|pi|claude) this exercises the exact production path:
explicit discovery selection, profile preparation, `CopiedAdapterFactory`
with the production allowlist, `LocalRuntimeCore.open`, one tiny real model
turn, terminal correlation and bounded shutdown. Authentication comes from
the user's existing provider configuration; nothing is read, copied or
printed. Logs only protocol metadata — never prompt output, model text,
stderr or secrets.
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
    CloseOperation, CoreError, EventCursor, ExecutionContext, LaunchIntent,
    LocalRuntimeCore, OpenOperation, OperationKey, SessionKey,
    ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.discovery import (
    candidate as discovery_candidate, candidate_pi_node_cli,
    probe_selected_claude, probe_selected_codex, probe_selected_pi,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory

_TERMINALS = {
    "codex_app_server": lambda native: native == "turn/completed",
    "pi_rpc": lambda native: native == "agent_settled",
    "claude_stream": lambda native: native.startswith("result:"),
}


async def _run(adapter: str, paths: dict[str, str]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(
            prefix=f"nexus-core-managed-{adapter}-") as directory:
        root = Path(directory)
        workspace = root / "ws"
        workspace.mkdir()
        environment_overlay: dict[str, str] = {
            name: value for name, value in os.environ.items()
            if name.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                                "PATH", "TEMP", "TMP", "LANG", "LC_ALL",
                                "TERM"}
        }
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            if name in os.environ:
                environment_overlay[name] = os.environ[name]
        if adapter == "codex_app_server":
            candidate = await probe_selected_codex(
                discovery_candidate("codex_app_server", paths["codex"],
                                     explicit=True),
                cwd=workspace, env=environment_overlay)
            environment_overlay["CODEX_HOME"] = paths["codex_home"]
        elif adapter == "pi_rpc":
            selected = candidate_pi_node_cli(paths["node"], paths["pi_cli"],
                                             explicit=True)
            candidate = await probe_selected_pi(selected, cwd=workspace,
                                                env=environment_overlay)
            environment_overlay["PI_CODING_AGENT_DIR"] = paths["pi_config"]
        else:
            candidate = await probe_selected_claude(
                discovery_candidate("claude_stream", paths["claude"],
                                    explicit=True),
                cwd=workspace, env=environment_overlay)

        async def environment(_prepared) -> dict[str, str]:
            return dict(environment_overlay)

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
            report["prepared_version"] = prepared.candidate.version
            report["prepared_architecture"] = prepared.candidate.architecture
            opened = await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), context)
            report["open_stage"] = opened.stage
            submitted = await runtime.submit(
                TurnOperation("turn", "session", "Reply with exactly: OK"),
                context)
            report["submit_stage"] = submitted.stage
            terminal = None

            async def wait_terminal():
                nonlocal terminal
                async for event in runtime.events(EventCursor(
                        "srv", "exe", "session", "epoch")):
                    if (event.payload.get("delivery_phase") == "terminal" and
                            _TERMINALS[adapter](event.native_type)):
                        terminal = event
                        return event

            event = await asyncio.wait_for(wait_terminal(), timeout=240)
            report["terminal_operation_id"] = event.operation_id
            report["terminal_outcome"] = event.payload.get("delivery_outcome")
            receipt = await journal.get_receipt(
                OperationKey("srv", "exe", "turn"))
            report["turn_receipt_stage"] = receipt.stage if receipt else None
            try:
                closed = await runtime.close(
                    CloseOperation("close", "session"), context)
                report["close_stage"] = closed.stage
            except CoreError as exc:
                # An honestly-unknown close (possible effect, unconfirmed
                # native stop) is a valid conservative outcome, not a probe
                # failure; shutdown below still contains the owned tree.
                report["close_stage"] = exc.code
            shutdown = await runtime.shutdown(ShutdownPolicy(5, 5))
            report["shutdown_outcome"] = shutdown.session_outcomes.get(
                SessionKey("srv", "exe", "session"))
        finally:
            try:
                await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            except CoreError:
                pass
            journal.close()
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adapter", choices=sorted(_TERMINALS))
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
    report = asyncio.run(_run(args.adapter, paths))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
