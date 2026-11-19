import asyncio
import os
import time
from dataclasses import replace
from uuid import uuid4

import pytest

from nexus_connector_core import ClaudeTerminalResumeGrant, CoreError, ExecutionContext, LaunchIntent
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.harness_configuration import validate_harness_settings
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.native import claude_terminal_resume
from nexus_connector_core.native.claude_saved_history import ClaudeSavedHistory
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.profiles import prepare_launch


@pytest.mark.skipif(os.name != "nt", reason="Reviewed Claude terminal launch is Windows only")
def test_claude_factory_refuses_wrong_or_stale_grants_before_provider_resolution(tmp_path, monkeypatch):
    binary = tmp_path / "claude.exe"
    binary.write_bytes(b"selected fixture build without a native implementation")
    candidate = InstallationCandidate("claude_stream", str(binary), fingerprint(binary), "explicit", "selected")
    monkeypatch.setattr(claude_terminal_resume, "_REVIEWED_FINGERPRINT", candidate.fingerprint)
    intent = LaunchIntent("agent", "workspace", "claude_stream",
        harness_settings=validate_harness_settings("claude_stream", {"permission_mode": "plan"}))
    prepared = prepare_launch(intent, candidate, str(tmp_path))
    context = ExecutionContext("server", "executor", "binding", "agent", "workspace", 1, 1, 1,
                               time.monotonic() + 60, frozenset({"runtime.open"}))
    history = ClaudeSavedHistory(str(uuid4()), str(tmp_path / "profile"), prepared.cwd,
                                 (1, 2), (1, 3), (1, 4), 99, "0" * 64)

    def changed():
        raise CoreError("PROFILE_DRIFT", "approved_profile", retry_safe=True)

    grant = ClaudeTerminalResumeGrant(history, "session", "server", "executor", "binding", "agent", "workspace",
        context.session_owner_generation, context.authorization_revision, context.configuration_revision,
        prepared.profile_fingerprint, prepared.root_fingerprint, changed)

    async def environment(_prepared):
        pytest.fail("A refused launch must not resolve provider credentials.")

    async def run():
        for supplied, target, expected in (
                (None, history.session_uuid, "BINDING_NOT_AUTHORIZED"),
                (grant, str(uuid4()), "BINDING_NOT_AUTHORIZED"),
                (replace(grant, configuration_revision=2), history.session_uuid, "BINDING_NOT_AUTHORIZED"),
                (replace(grant, session_id="different"), history.session_uuid, "BINDING_NOT_AUTHORIZED"),
                (grant, history.session_uuid, "PROFILE_DRIFT")):
            async def approve(*_args):
                return supplied

            factory = CopiedAdapterFactory(environment, claude_resume=approve)
            try:
                with pytest.raises(CoreError, match=expected) as refused:
                    await factory.open(prepared, "session", context, stream_epoch="stream",
                        resume_claude_session_id=target, opening_guard=object(),
                        process_launch=object(), process_birth_recorder=object())
                assert refused.value.retry_safe and not refused.value.possible_effect
            finally:
                factory.close()

    asyncio.run(run())
