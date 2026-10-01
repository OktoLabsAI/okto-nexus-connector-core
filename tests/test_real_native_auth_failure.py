"""Opt-in native missing-login test with a fresh, isolated provider home."""
import asyncio
import os
from pathlib import Path
import sys
import time

import pytest

from nexus_connector_core import ExecutionContext, OperationKey
from nexus_connector_core.discovery import candidate
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import LaunchIntent, OpenOperation, ShutdownPolicy, TurnOperation
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.runtime import LocalRuntimeCore


@pytest.mark.skipif(os.environ.get("OKTO_NEXUS_REAL_AUTH_FAILURES") != "1" or sys.platform != "win32",
                    reason="The Windows real missing-login campaign is opt-in.")
def test_real_claude_missing_login_has_durable_authentication_error(tmp_path):
    binary = Path.home() / ".local/bin/claude.exe"
    assert binary.is_file()
    home = tmp_path / "empty-provider-home"
    home.mkdir()
    async def run():
        async def environment(prepared):
            return {"HOME": str(home), "USERPROFILE": str(home),
                    "CLAUDE_CONFIG_DIR": str(home / "claude"),
                    "APPDATA": str(home / "AppData/Roaming"),
                    "LOCALAPPDATA": str(home / "AppData/Local")}
        observed = candidate("claude_stream", binary, explicit=True)
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(journal, CopiedAdapterFactory(environment),
            candidates={"claude_stream": observed}, workspace_roots={"ws": str(tmp_path)})
        authority = ExecutionContext("srv", "exe", "binding", "agent", "ws", 1, 1, 1,
            time.monotonic() + 60, frozenset({"runtime.open", "turn.submit", "runtime.close"}))
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", "claude_stream"), authority)
            await runtime.open(OpenOperation("open", "session", "epoch", prepared), authority)
            await runtime.submit(TurnOperation("turn", "session", "Do not call tools. Reply with OK."), authority)
            async with asyncio.timeout(30):
                while True:
                    receipt = await journal.get_receipt(OperationKey("srv", "exe", "turn"))
                    if receipt and receipt.stage == "FAILED":
                        break
                    await asyncio.sleep(.05)
            assert receipt.error_code == "PROVIDER_AUTH_REQUIRED"
            assert receipt.possible_effect and not receipt.retry_safe
        finally:
            await runtime.shutdown(ShutdownPolicy(2, 2))
            journal.close()
    asyncio.run(run())
