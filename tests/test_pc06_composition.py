"""PC06: public composition, protocol completeness, private-import bans."""

import ast
import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nexus_connector_core import (
    ExecutionContext, InstallationCandidate, LaunchIntent,
    OpenOperation, SessionKey, ShutdownPolicy, create_runtime,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.ports import RuntimeCore
from nexus_connector_core.runtime import LocalRuntimeCore

REPO = Path(__file__).resolve().parent.parent
PRIVATE_MODULES = {
    "nexus_connector_core.native.runtime_bridge",
    "nexus_connector_core.native.adapters",
    "nexus_connector_core.offloop",
}


class _Native:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()

    async def send(self, verb, payload, operation_id, *,
                   expected_turn_id=None):
        pass

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED", "IDLE")


class _Factory:
    def __init__(self):
        self.native = _Native()

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


def _candidate(tmp_path):
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary")
    return InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary), "explicit",
        "selected")


def test_create_runtime_validates_inputs_before_any_effect(tmp_path):
    candidate = _candidate(tmp_path)
    with pytest.raises(TypeError):
        create_runtime(journal=object(), environment=None,
                       candidates={"codex_app_server": candidate},
                       workspace_roots={"ws": str(tmp_path)})
    with pytest.raises(TypeError):
        create_runtime(journal=object(), environment=lambda p: {},
                       candidates={}, workspace_roots={"ws": str(tmp_path)})
    with pytest.raises(TypeError):
        create_runtime(journal=object(), environment=lambda p: {},
                       candidates={"codex_app_server": "not-a-candidate"},
                       workspace_roots={"ws": str(tmp_path)})
    with pytest.raises(TypeError):
        create_runtime(journal=object(), environment=lambda p: {},
                       candidates={"codex_app_server": candidate},
                       workspace_roots={}, native_factory=_Factory())
    with pytest.raises(TypeError):
        create_runtime(journal=object(), environment=lambda p: {},
                       candidates={"codex_app_server": candidate},
                       workspace_roots={"ws": str(tmp_path)},
                       native_approvals_enabled="yes")
    with pytest.raises(TypeError):
        create_runtime(journal=object(), environment=lambda p: {},
                       candidates={"codex_app_server": candidate},
                       workspace_roots={"ws": str(tmp_path)},
                       codex_resume=object())


def test_rc_06_04_runtime_core_protocol_is_complete():
    if hasattr(RuntimeCore, "__protocol_attrs__"):
        expected = set(RuntimeCore.__protocol_attrs__)
    else:  # Python 3.11: protocol members live in __annotations__
        expected = {name for name in RuntimeCore.__annotations__
                    if not name.startswith("_")}
    missing = expected - {
        name for name in dir(LocalRuntimeCore) if not name.startswith("_")}
    assert not missing, sorted(missing)


def test_rc_06_06_two_runtimes_keep_isolated_resources(tmp_path):
    async def run():
        journal_a = SQLiteJournal(tmp_path / "a.db")
        journal_b = SQLiteJournal(tmp_path / "b.db")
        runtime_a = create_runtime(
            journal=journal_a, environment=lambda p: {},
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory())
        runtime_b = create_runtime(
            journal=journal_b, environment=lambda p: {},
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory())
        context = ExecutionContext(
            "srv", "exe-a", "binding", "agent", "ws", 1, 1, 1,
            time.monotonic() + 60, frozenset({"runtime.open"}))
        try:
            prepared = await runtime_a.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), context)
            await runtime_a.open(OpenOperation(
                "open", "session", "epoch", prepared), context)
            # Closing runtime A's world must not disturb B's journal.
            await runtime_a.shutdown(ShutdownPolicy())
            lease_b = await runtime_b.persisted_lease(SessionKey(
                "srv", "exe-a", "session"))
            assert lease_b is None
            assert journal_b.worker_metrics()["worker_alive"] is True
        finally:
            await runtime_b.shutdown(ShutdownPolicy())
            journal_a.close()
            journal_b.close()

    asyncio.run(run())


@pytest.mark.parametrize("example", ["embedded_consumer", "remote_consumer"])
def test_rc_06_01_02_examples_run_with_public_imports_only(example):
    import os
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run(
        [sys.executable, str(REPO / "examples" / f"{example}.py")],
        capture_output=True, text=True, timeout=60, env=environment)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_rc_06_03_private_imports_banned_in_examples_and_smoke():
    for path in [REPO / "examples" / "embedded_consumer.py",
                 REPO / "examples" / "remote_consumer.py",
                 REPO / "tools" / "consumer_smoke.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ""
                for alias in node.names:
                    assert alias.name not in PRIVATE_MODULES, (path, alias.name)
                continue
            else:
                continue
            assert module not in PRIVATE_MODULES, (path, module)
            assert not module.startswith("nexus_connector_core.native."), (
                path, module)


def _systemroot():
    import os
    return os.environ.get("SYSTEMROOT", "")


def _path():
    import os
    return os.environ.get("PATH", "")


def _temp():
    import os
    return os.environ.get("TEMP", os.environ.get("TMP", ""))
