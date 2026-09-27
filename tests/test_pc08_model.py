"""PC08: explicit model wiring, defaults and hostile input."""

import asyncio
import time

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, LaunchIntent,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.profiles import prepare_launch


def _candidate(tmp_path, adapter_id="claude_stream", name="claude"):
    binary = tmp_path / name
    binary.write_bytes(b"synthetic binary")
    return InstallationCandidate(
        adapter_id, str(binary), fingerprint(binary), "explicit", "selected")


def test_rc_08_04_absent_model_keeps_documented_defaults(tmp_path):
    candidate = _candidate(tmp_path)
    launch = prepare_launch(
        LaunchIntent("ag", "ws", "claude_stream"), candidate, tmp_path)
    assert "--model" not in launch.argv
    assert launch.intent.model is None
    # Codex: no overrides requested when the intent carries no model.
    codex = _candidate(tmp_path, "codex_app_server", "codex")
    launch_codex = prepare_launch(
        LaunchIntent("ag", "ws", "codex_app_server"), codex, tmp_path)
    assert launch_codex.argv == (str((tmp_path / "codex").resolve()),
                                 "app-server")


@pytest.mark.parametrize("model", ["", "x" * 201, 5, True])
def test_rc_08_08_invalid_model_refused_before_preparation(tmp_path, model):
    candidate = _candidate(tmp_path)
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        prepare_launch(LaunchIntent("ag", "ws", "claude_stream", model=model),
                       candidate, tmp_path)


def test_rc_08_08_unicode_and_spaces_travel_as_single_tokens(tmp_path):
    candidate = _candidate(tmp_path)
    model = "modelo á ; rm -rf / && echo pwned"
    launch = prepare_launch(
        LaunchIntent("ag", "ws", "claude_stream", model=model),
        candidate, tmp_path)
    index = launch.argv.index("--model")
    assert launch.argv[index + 1] == model  # one structured token, no shell


def test_rc_08_01_codex_model_reaches_thread_start_overrides(tmp_path):
    import nexus_connector_core.native.runtime_bridge as bridge_module

    async def run():
        captured = {}

        class Recording:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def start(self, **kwargs):
                from nexus_connector_core.native.adapter_types import (
                    HarnessCapabilities, HarnessSession,
                )
                return HarnessSession(
                    "native-session", "codex", kwargs.get("owning_agent_id",
                                                          "agent"),
                    "STARTING", HarnessCapabilities(False, "IMMEDIATE", False,
                                                    True, True),
                    "2026-09-26T00:00:00Z")

            def close(self):
                gate = getattr(self, "_stream_gate", None)
                if gate is not None:
                    gate.set()

            def events(self):
                import threading as _threading
                # A live stream never ends on its own; it ends when the
                # connector closes. The bridge polls via to_thread, so the
                # generator must release the thread promptly on close.
                gate = _threading.Event()
                self._stream_gate = gate
                while not gate.is_set():
                    gate.wait(0.05)
                return
                yield

            def observe_lifecycle(self, session):
                return {"stop_observed": True}

            def force_stop(self):
                gate = getattr(self, "_stream_gate", None)
                if gate is not None:
                    gate.set()

        original_loader = bridge_module.load_adapter
        original_qualified = bridge_module.qualified_build
        bridge_module.load_adapter = lambda adapter_id: Recording
        bridge_module.qualified_build = lambda *a, **k: True
        journal = SQLiteJournal(tmp_path / "journal.db")
        try:

            async def environment(_prepared):
                return {}

            from nexus_connector_core import LocalRuntimeCore
            runtime = LocalRuntimeCore(
                journal, bridge_module.CopiedAdapterFactory(environment),
                candidates={"codex_app_server": _candidate(
                    tmp_path, "codex_app_server", "codex")},
                workspace_roots={"ws": str(tmp_path)})
            authority = ExecutionContext(
                "srv", "exe", "b", "ag", "ws", 1, 1, 3,
                time.monotonic() + 60,
                frozenset({"runtime.open"}))
            prepared = await runtime.prepare(
                LaunchIntent("ag", "ws", "codex_app_server",
                             model="gpt-5.3-codex"), authority)
            from nexus_connector_core import OpenOperation, ShutdownPolicy
            await runtime.open(OpenOperation(
                "open", "session", "epoch", prepared), authority)
            assert captured.get("thread_start_overrides") == {
                "model": "gpt-5.3-codex"}
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
        finally:
            bridge_module.load_adapter = original_loader
            bridge_module.qualified_build = original_qualified
            journal.close()

    asyncio.run(run())
