"""Launch a new or retired Claude context in the Core-owned terminal."""

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
from uuid import uuid4

from ..models import CoreError, EffectRejected
from .claude_saved_history import (
    ClaudeSavedHistory,
    claude_history_path,
    observe_claude_saved_history,
)
from .claude_terminal_generation import ClaudeGenerationTrace, observe_claude_generation
from .claude_terminal_owner import (
    FreshClaudeTerminalIdentity,
    claude_terminal_directories_current,
    has_default_claude_interrupt_key,
    observe_claude_chat_turn,
    observe_claude_finished_turn,
    observe_claude_interrupted_turn,
    observe_claude_terminal_owner,
)
from .claude_terminal_prompt import ClaudeTerminalPromptGate
from .claude_terminal_submission import ClaudeTerminalSession
from .redaction import NativeSecretRedactor, credential_values
from .saved_history_file import file_identity, plain_path

_REVIEWED_FINGERPRINT = "sha256:551d573567b46ce78aba1b20beb20ac2494f5f8adffd1b41dfd269a96e1d9839"
_STREAM_FRONT = ("-p", "--output-format", "stream-json", "--input-format", "stream-json",
                 "--verbose", "--include-partial-messages")
_START_TIMEOUT = 18.0
_BIRTH_TIMEOUT = 10.0
_STAGE = "claude_resume"


@dataclass(frozen=True, slots=True)
class ClaudeTerminalFreshGrant:
    """Trusted approval of the profile and state directory for a new session."""

    state_home: str = field(repr=False)
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
    question_only: bool = False
    read_approval: bool = False


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
    question_only: bool = False
    read_approval: bool = False


def require_claude_resume_grant(grant, native_id, prepared, session_id, context):
    if (type(grant) is not ClaudeTerminalResumeGrant
            or type(grant.history) is not ClaudeSavedHistory
            or grant.history.session_uuid != native_id
            or type(grant.history.workspace) is not str
            or type(grant.history.state_home) is not str
            or Path(grant.history.workspace) != Path(prepared.cwd)
            or not _same_grant_scope(grant, prepared, session_id, context)):
        raise CoreError("BINDING_NOT_AUTHORIZED", _STAGE, retry_safe=True)


def require_claude_fresh_grant(grant, prepared, session_id, context):
    if (type(grant) is not ClaudeTerminalFreshGrant or type(grant.state_home) is not str
            or not Path(grant.state_home).is_absolute()
            or not _same_grant_scope(grant, prepared, session_id, context)):
        raise CoreError("BINDING_NOT_AUTHORIZED", "claude_terminal_open", retry_safe=True)


def _same_grant_scope(grant, prepared, session_id, context):
    return (grant.session_id == session_id
            and grant.profile_fingerprint == prepared.profile_fingerprint
            and grant.root_fingerprint == prepared.root_fingerprint
            and type(grant.question_only) is bool and type(grant.read_approval) is bool
            and not (grant.question_only and grant.read_approval)
            and callable(grant.require_current)
            and all(getattr(grant, key) == getattr(context, key) for key in (
                "server_id", "executor_id", "binding_id", "agent_id", "workspace_id", "session_owner_generation",
                "authorization_revision", "configuration_revision")))


def reviewed_claude_terminal_candidate(candidate):
    return (sys.platform == "win32" and candidate.adapter_id == "claude_stream"
            and candidate.fingerprint == _REVIEWED_FINGERPRINT)


def require_reviewed_claude_terminal(prepared, process_launch, recorder, guard):
    if (not reviewed_claude_terminal_candidate(prepared.candidate)
            or prepared.intent.harness_settings.permission_mode != "plan"
            or prepared.argv[1:1 + len(_STREAM_FRONT)] != _STREAM_FRONT
            or process_launch is None or recorder is None or guard is None):
        raise CoreError("CAPABILITY_UNSUPPORTED", _STAGE, retry_safe=True)


def _new_terminal_identity(state_home, workspace):
    return FreshClaudeTerminalIdentity(
        str(uuid4()), state_home, workspace,
        file_identity(plain_path(Path(state_home), directory=True)),
        file_identity(plain_path(Path(workspace), directory=True)))


def _require_empty_context(history, transcript):
    home, workspace = Path(history.state_home), Path(history.workspace)
    try:
        if claude_terminal_directories_current(history, home, workspace):
            for parent in reversed(transcript.parents):
                try:
                    plain_path(parent, directory=True)
                except FileNotFoundError:
                    break
            try:
                transcript.lstat()
            except FileNotFoundError:
                return
    except (OSError, ValueError):
        pass
    raise CoreError("PROFILE_DRIFT", "claude_terminal_open", retry_safe=True)


def _observe_owned_history(terminal, history, birth):
    if not observe_claude_terminal_owner(terminal, history, birth):
        return None
    current = observe_claude_saved_history(history.state_home, history.session_uuid, history.workspace)
    if (current is None or current.home_identity != history.home_identity
            or current.workspace_identity != history.workspace_identity):
        return None
    if isinstance(history, FreshClaudeTerminalIdentity):
        if not history.match_file(current.file_identity):
            return None
    elif current.file_identity != history.file_identity:
        return None
    if not observe_claude_terminal_owner(terminal, history, birth):
        return None
    return current


async def open_claude_terminal(
    prepared, command, env, session_id, context, stream_epoch, *, grant, process_launch,
    process_birth_recorder, revalidate_launch, verify_content, resources,
):
    from .claude_terminal_reader import ClaudeTerminalText
    from .process.windows_terminal import OwnedWindowsTerminal

    fresh = type(grant) is ClaudeTerminalFreshGrant
    stage = "claude_terminal_open" if fresh else _STAGE
    if fresh:
        try:
            history = await asyncio.to_thread(_new_terminal_identity, grant.state_home, prepared.cwd)
        except (OSError, ValueError) as error:
            raise CoreError("PROFILE_DRIFT", stage, retry_safe=True) from error
    else:
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
        raise CoreError("PROFILE_DRIFT", stage, retry_safe=True)
    identity = process_launch.identity
    if (identity.platform != "win32" or identity.containment != "windows_job"
            or (identity.key.server_id, identity.key.executor_id, identity.key.session_id) !=
               (context.server_id, context.executor_id, session_id)):
        raise CoreError("PROCESS_LAUNCH_CONFLICT", stage, retry_safe=True)

    # The Core already recorded SUBMISSION_STARTED before the prompt gate
    # arms and rechecks the exact operation at the hook's write frontier.
    gate = ClaudeTerminalPromptGate(history.session_uuid, prepared.cwd, "plan", lambda _operation: True,
                                  observe_results=True, startup=(str(powershell), transcript),
                                  startup_source="startup" if fresh else "resume",
                                  allow_questions=grant.question_only or grant.read_approval,
                                  allow_read=grant.read_approval)
    revalidate = partial(revalidate_launch, stage)
    await asyncio.to_thread(gate.__enter__)
    terminal = None
    trace = None
    loop = asyncio.get_running_loop()
    try:
        settings, hook_env = gate.launch_settings()
        if any(key.upper() in hook_env for key in env):
            raise CoreError("BINDING_NOT_AUTHORIZED", stage, retry_safe=True)
        child_env = env | hook_env
        redactor = NativeSecretRedactor(credential_values(child_env))
        argv = (command[0], "--session-id" if fresh else "--resume", history.session_uuid,
                *command[1 + len(_STREAM_FRONT):],
                "--settings", json.dumps(settings, separators=(",", ":")))
        try:
            trace = await asyncio.to_thread(ClaudeGenerationTrace)
        except (CoreError, OSError):
            pass  # The terminal still supports read attachment and canonical prompts.
        if trace is not None:
            argv += trace.arguments()

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
            if fresh:
                _require_empty_context(history, transcript)
            elif observe_claude_saved_history(history.state_home, history.session_uuid, history.workspace) != history:
                raise CoreError("PROFILE_DRIFT", stage, retry_safe=True)
            verify_content()
            revalidate()
            return OwnedWindowsTerminal(argv, cwd=prepared.cwd, env=child_env,
                                       container_id=identity.container_id, birth_observer=record_birth,
                                       output_projection=ClaudeTerminalText(redactor))

        default_keys = partial(has_default_claude_interrupt_key, history)
        allow_interrupt = default_keys if await asyncio.to_thread(default_keys) else None
        terminal = await process_launch.produce(validate_authority=revalidate, start=start)
        birth = await asyncio.to_thread(lambda: terminal.birth)
        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            revalidate()
            if await asyncio.to_thread(terminal.poll) is not None:
                break
            if gate.startup_confirmed.is_set() and await asyncio.to_thread(
                    observe_claude_terminal_owner, terminal, history, birth):
                if fresh:
                    await asyncio.to_thread(_require_empty_context, history, transcript)
                await asyncio.to_thread(grant.require_current)
                await asyncio.to_thread(verify_content)
                revalidate()
                generation = partial(observe_claude_generation, terminal, history, birth, trace) if trace else None
                return ClaudeTerminalSession(
                    terminal, gate, native_id="claude_" + token_hex(16), session_id=session_id,
                    stream_epoch=stream_epoch, context=context, redactor=redactor,
                    observe_finished=partial(observe_claude_finished_turn, terminal, history, birth),
                    observe_chat=partial(observe_claude_chat_turn, terminal, history, birth),
                    observe_history=partial(_observe_owned_history, terminal, history, birth),
                    observe_interrupted=partial(observe_claude_interrupted_turn, terminal, history, birth),
                    observe_generation=generation, require_current=grant.require_current,
                    allow_interrupt=allow_interrupt,
                    resources=(*resources, trace) if trace is not None else resources)
            await asyncio.sleep(.1)
        raise EffectRejected("The Claude terminal did not confirm the exact session.",
                             failure_code="NATIVE_STARTUP_FAILED")
    except BaseException as error:
        try:
            if terminal is not None:
                await asyncio.to_thread(terminal.close)
        finally:
            try:
                await asyncio.to_thread(gate.__exit__, None, None, None)
            finally:
                if trace is not None:
                    await asyncio.to_thread(trace.close)
        if terminal is not None and isinstance(error, CoreError) and not error.possible_effect:
            raise CoreError(error.code, stage, possible_effect=True) from error
        raise
