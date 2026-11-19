"""Launch an authorized saved Claude context in the Core-owned terminal."""

import asyncio
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from secrets import token_hex

from ..models import CoreError, EffectRejected
from .claude_saved_history import ClaudeSavedHistory, claude_history_path, observe_claude_saved_history
from .claude_terminal_owner import (
    observe_claude_finished_turn,
    observe_claude_interrupted_turn,
    observe_claude_terminal_owner,
)
from .claude_terminal_prompt import ClaudeTerminalPromptGate
from .claude_terminal_submission import ClaudeTerminalSession
from .redaction import NativeSecretRedactor, credential_values

_REVIEWED_FINGERPRINT = "sha256:551d573567b46ce78aba1b20beb20ac2494f5f8adffd1b41dfd269a96e1d9839"
_STREAM_FRONT = ("-p", "--output-format", "stream-json", "--input-format", "stream-json",
                 "--verbose", "--include-partial-messages")
_START_TIMEOUT = 18.0
_BIRTH_TIMEOUT = 10.0
_STAGE = "claude_resume"


@dataclass(frozen=True, slots=True)
class ClaudeTerminalResumeGrant:
    """Trusted host proof of a retired exclusive source and reviewed profile."""

    history: ClaudeSavedHistory = field(repr=False)
    session_id: str
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    workspace_id: str
    session_owner_generation: int
    authorization_revision: int
    configuration_revision: int
    profile_fingerprint: str
    root_fingerprint: str
    require_current: Callable[[], None] = field(repr=False)


def require_claude_resume_grant(grant, native_id, prepared, session_id, context):
    if (type(grant) is not ClaudeTerminalResumeGrant
            or type(grant.history) is not ClaudeSavedHistory
            or grant.history.session_uuid != native_id
            or type(grant.history.workspace) is not str
            or type(grant.history.state_home) is not str
            or Path(grant.history.workspace) != Path(prepared.cwd)
            or grant.session_id != session_id
            or grant.profile_fingerprint != prepared.profile_fingerprint
            or grant.root_fingerprint != prepared.root_fingerprint
            or not callable(grant.require_current)
            or any(getattr(grant, key) != getattr(context, key) for key in (
                "server_id", "executor_id", "binding_id", "agent_id", "workspace_id", "session_owner_generation",
                "authorization_revision", "configuration_revision"))):
        raise CoreError("BINDING_NOT_AUTHORIZED", _STAGE, retry_safe=True)


def require_reviewed_claude_terminal(prepared, process_launch, recorder, guard):
    if (sys.platform != "win32" or prepared.candidate.fingerprint != _REVIEWED_FINGERPRINT
            or prepared.intent.harness_settings.permission_mode != "plan"
            or prepared.argv[1:1 + len(_STREAM_FRONT)] != _STREAM_FRONT
            or process_launch is None or recorder is None or guard is None):
        raise CoreError("CAPABILITY_UNSUPPORTED", _STAGE, retry_safe=True)


async def open_saved_claude_terminal(
    prepared, command, env, session_id, context, stream_epoch, *, grant, process_launch,
    process_birth_recorder, revalidate_launch, verify_content, resources,
):
    from .process.windows_terminal import OwnedWindowsTerminal

    history = grant.history
    # No home guessing, implicit migration or re-use of a stale target.
    raw_home = env.get("CLAUDE_CONFIG_DIR")
    transcript = claude_history_path(history.state_home, history.session_uuid, history.workspace)
    system_root = os.environ.get("SystemRoot")
    powershell = (Path(system_root) / "System32/WindowsPowerShell/v1.0/powershell.exe"
                  if type(system_root) is str else None)
    if (type(raw_home) is not str or Path(raw_home) != Path(history.state_home)
            or transcript is None or powershell is None or not powershell.is_absolute()
            or not await asyncio.to_thread(powershell.is_file)):
        raise CoreError("PROFILE_DRIFT", _STAGE, retry_safe=True)
    identity = process_launch.identity
    if (identity.platform != "win32" or identity.containment != "windows_job"
            or (identity.key.server_id, identity.key.executor_id, identity.key.session_id) !=
               (context.server_id, context.executor_id, session_id)):
        raise CoreError("PROCESS_LAUNCH_CONFLICT", _STAGE, retry_safe=True)

    # The Core already recorded SUBMISSION_STARTED before the prompt gate
    # arms and rechecks the exact operation at the hook's write frontier.
    gate = ClaudeTerminalPromptGate(history.session_uuid, prepared.cwd, "plan", lambda _operation: True,
                                  observe_results=True, startup=(str(powershell), transcript))
    revalidate = partial(revalidate_launch, _STAGE)
    await asyncio.to_thread(gate.__enter__)
    terminal = None
    loop = asyncio.get_running_loop()
    try:
        settings, hook_env = gate.launch_settings()
        if any(key.upper() in hook_env for key in env):
            raise CoreError("BINDING_NOT_AUTHORIZED", _STAGE, retry_safe=True)
        child_env = env | hook_env
        redactor = NativeSecretRedactor(credential_values(child_env))
        argv = (command[0], "--resume", history.session_uuid, *command[1 + len(_STREAM_FRONT):],
                "--settings", json.dumps(settings, separators=(",", ":")))

        def record_birth(evidence):
            pending = process_birth_recorder(evidence)
            try:
                recorded = asyncio.run_coroutine_threadsafe(pending, loop)
            except BaseException:
                pending.close()
                raise
            recorded.result(timeout=_BIRTH_TIMEOUT)
            revalidate()

        def start():
            revalidate()
            grant.require_current()
            if observe_claude_saved_history(history.state_home, history.session_uuid, history.workspace) != history:
                raise CoreError("PROFILE_DRIFT", _STAGE, retry_safe=True)
            verify_content()
            revalidate()
            return OwnedWindowsTerminal(argv, cwd=prepared.cwd, env=child_env,
                                       container_id=identity.container_id, birth_observer=record_birth)

        terminal = await process_launch.produce(validate_authority=revalidate, start=start)
        birth = await asyncio.to_thread(lambda: terminal.birth)
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            revalidate()
            if await asyncio.to_thread(terminal.poll) is not None:
                break
            if gate.startup_confirmed.is_set() and await asyncio.to_thread(
                    observe_claude_terminal_owner, terminal, history, birth):
                await asyncio.to_thread(grant.require_current)
                await asyncio.to_thread(verify_content)
                revalidate()
                return ClaudeTerminalSession(
                    terminal, gate, native_id="claude_" + token_hex(16), session_id=session_id,
                    stream_epoch=stream_epoch, context=context, redactor=redactor,
                    observe_finished=partial(observe_claude_finished_turn, terminal, history, birth),
                    observe_interrupted=partial(observe_claude_interrupted_turn, terminal, history, birth),
                    require_current=grant.require_current, resources=resources)
            await asyncio.sleep(.1)
        raise EffectRejected("The Claude terminal did not confirm the exact saved context.",
                             failure_code="NATIVE_STARTUP_FAILED")
    except BaseException as error:
        try:
            if terminal is not None:
                await asyncio.to_thread(terminal.close)
        finally:
            await asyncio.to_thread(gate.__exit__, None, None, None)
        if terminal is not None and isinstance(error, CoreError) and not error.possible_effect:
            raise CoreError(error.code, _STAGE, possible_effect=True) from error
        raise
