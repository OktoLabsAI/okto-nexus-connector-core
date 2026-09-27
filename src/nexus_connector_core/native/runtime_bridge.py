"""Private bridge from copied synchronous adapters to the async Core port."""

from __future__ import annotations

import asyncio
import re
import sys
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from ..models import (CoreError, ExecutionContext, PreparedLaunch,
                      ProcessBirthEvidence, RuntimeEvent)
from ..harness_config import _token_env_name
from ..pi_extension_resource import PiNativeActionLaunch
from .adapter_types import (HarnessCommand, HarnessEvent, HarnessSession,
                            NativeAdapterError, RuntimeCommandNotSent)
from .adapters.compatibility import qualified_build
from .event_ingest import translate_native_event
from .registry import adapter_spec, load_adapter
from .redaction import NativeSecretRedactor, credential_values
from .process import snapshot_owned_process_birth


@dataclass(frozen=True, slots=True)
class CodexResumeGrant:
    """Trusted-host proof for binding one stored Codex thread to one open."""

    thread_id: str
    session_id: str
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    workspace_id: str
    session_owner_generation: int
    candidate_fingerprint: str
    root_fingerprint: str
    profile_fingerprint: str
    terminal_observed: bool
    persisted_rollout_observed: bool
    exclusive_owner: bool


class _CopiedConnector(Protocol):
    def start(self, *, owning_agent_id: str) -> HarnessSession: ...
    def send(self, session: HarnessSession, command: HarnessCommand) -> None: ...
    def events(self) -> Iterator[HarnessEvent]: ...
    def close(self) -> None: ...
    def force_stop(self) -> None: ...
    def observe_lifecycle(self, session: HarnessSession) -> Mapping[str, Any]: ...


def _next_event(iterator: Iterator[HarnessEvent]) -> HarnessEvent | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


class EffectFence:
    """Thread-safe pre-dispatch guard shared with the native bridge (PC03).

    The runtime trips it whenever the in-memory admission fence closes
    (expiry/revocation/closing/fault). The copied-adapter bridge checks it
    on the loop AND inside the dispatch thread immediately before the
    native write/spawn - the closest point to the effect (RC-03-03: a
    thread that starts late must not write under stale authorization).
    Containment controls (interrupt/close) stay allowed past a lease
    deadline by contract; everything else fails closed before the write.
    """

    __slots__ = ("_probe",)

    def __init__(self, probe=None):
        self._probe = probe

    def check(self, action: str) -> None:
        probe = self._probe
        if probe is None:
            return
        closed, closing, revoked, expired, faulted = probe()
        if closed:
            reason, code = "session closed before dispatch", "SESSION_CLOSED"
        elif revoked:
            reason, code = "authorization revoked before dispatch", "AGENT_REVOKED"
        elif faulted:
            reason, code = ("event stream unavailable before dispatch",
                            "EVENT_STREAM_UNAVAILABLE")
        elif closing and action not in {"interrupt", "end"}:
            reason, code = "session closing before dispatch", "SESSION_CLOSING"
        elif (expired and
                action not in {"interrupt", "end"}):
            reason, code = "lease expired before dispatch", "AGENT_REVOKED"
        else:
            return
        raise RuntimeCommandNotSent(reason, code=code)


class CopiedAdapterSession:
    def __init__(self, connector: _CopiedConnector, session: HarnessSession,
                 *, session_id: str, stream_epoch: str,
                 context: ExecutionContext,
                 redactor: NativeSecretRedactor | None = None):
        self._connector = connector
        self._session = session
        self._session_id = session_id
        self._epoch = stream_epoch
        self._context = context
        self._redactor = redactor or NativeSecretRedactor()
        self.native_id = session.session_id
        self._closed = False
        self._close_started = False
        self._end_attempted = False
        self._end_sent = False
        self._active_operation_id: str | None = None
        self._active_turn_id: str | None = None
        self._pi_started_for_active = False
        self._last_outcome: str | None = None
        self._recent_codex_turn_ids: deque[str] = deque()
        self._recent_codex_turn_set: set[str] = set()

    def _remember_codex_turn(self, turn_id: str) -> None:
        if len(self._recent_codex_turn_ids) >= 256:
            self._recent_codex_turn_set.remove(
                self._recent_codex_turn_ids.popleft())
        self._recent_codex_turn_ids.append(turn_id)
        self._recent_codex_turn_set.add(turn_id)

    def owned_process_birth(self) -> ProcessBirthEvidence | None:
        """Historical birth token, only for a Core-owned child container."""
        process = getattr(self._connector, "_proc", None)
        if process is None:
            return None  # External attach has no Core-owned process.
        return snapshot_owned_process_birth(process)

    def active_turn(self) -> bool:
        """Whether a native turn was sent without a correlated terminal event."""
        return self._active_operation_id is not None

    async def send(self, verb: str, payload: Mapping[str, str],
                   operation_id: str, *,
                   expected_turn_id: str | None = None) -> None:
        if self._close_started:
            raise CoreError("SESSION_CLOSED", "native_send")
        if verb in {"interrupt", "steer"}:
            if self._active_operation_id is None:
                raise RuntimeCommandNotSent("no active turn to control",
                                            code="STALE_TURN")
            if (expected_turn_id is not None and
                    expected_turn_id != self._active_turn_id):
                raise RuntimeCommandNotSent("expected native turn is not active",
                                            code="STALE_TURN")
            if (verb == "steer" and
                    self._session.harness_kind == "pi" and
                    not self._pi_started_for_active):
                # Pi's wire carries no native turn ID, so the only honest
                # ID-less steer target is the agent run this bridge has
                # observed starting for the active submit. Refusing before
                # the write keeps it a durable safe failure, never a guess
                # that lands on a turn that never started.
                raise RuntimeCommandNotSent(
                    "no started pi agent run to steer", code="STALE_TURN")
        if verb == "send_turn":
            if self._active_operation_id is not None:
                raise CoreError("STALE_TURN", "native_send")
            # Set before calling the blocking native port: a terminal event
            # may arrive before the synchronous send returns.
            self._active_operation_id = operation_id
            self._active_turn_id = None
            self._pi_started_for_active = False
            self._last_outcome = None
        native_payload = dict(payload)
        if verb == "send_turn" and self._session.harness_kind == "claude_code":
            native_payload = {"content": native_payload["text"]}
        command = HarnessCommand(self._session.session_id, verb, native_payload,
                                 operation_id=operation_id,
                                 expected_turn_id=expected_turn_id)
        try:
            fence = getattr(self, "effect_fence", None)
            if fence is not None:
                # Loop-side check: fail fast, before paying for the thread
                # hop. Thread-side check happens at the closest point to
                # the native write/spawn (RC-03-03): the thread may start
                # late.
                fence.check(command.verb)

                def _guarded_dispatch() -> None:
                    fence.check(command.verb)
                    self._connector.send(self._session, command)

                await asyncio.to_thread(_guarded_dispatch)
            else:
                await asyncio.to_thread(self._connector.send,
                                        self._session, command)
        except RuntimeCommandNotSent:
            if verb == "send_turn":
                self._active_operation_id = None
                self._active_turn_id = None
                self._pi_started_for_active = False
            raise
        except NativeAdapterError as exc:
            # Only the adapter's explicit pre-write evidence may become a
            # durable safe failure. A write/flush error remains uncertain.
            if exc.details.get("not_sent") is not True:
                raise
            if verb == "send_turn":
                self._active_operation_id = None
                self._active_turn_id = None
                self._pi_started_for_active = False
            raise RuntimeCommandNotSent(exc.message, code=exc.code.value) from exc

    async def reply_native_approval(
            self, request: Mapping[str, object], decision: str,
            operator_response: Mapping[str, object] | None) -> None:
        """Reply only to a still-active adapter-owned native request."""
        from .native_inputs import INPUT_METHODS

        method = request.get("method")
        params = request.get("params")
        if self._close_started or self._active_operation_id is None:
            raise RuntimeCommandNotSent("native approval turn is not active",
                                        code="STALE_TURN")
        if method in {"item/commandExecution/requestApproval",
                      "item/fileChange/requestApproval", *INPUT_METHODS}:
            if (self._session.harness_kind != "codex" or
                    not isinstance(params, dict) or
                    params.get("turnId") != self._active_turn_id):
                raise RuntimeCommandNotSent("native approval turn changed",
                                            code="STALE_TURN")
        elif method == "control_request:can_use_tool":
            if self._session.harness_kind != "claude_code":
                raise RuntimeCommandNotSent("native approval adapter changed",
                                            code="STALE_TURN")
        else:
            raise RuntimeCommandNotSent("native approval method unsupported",
                                        code="CAPABILITY_UNSUPPORTED")
        reply = getattr(self._connector, "reply_native_approval", None)
        if not callable(reply):
            raise RuntimeCommandNotSent("native approval unavailable",
                                        code="CAPABILITY_UNSUPPORTED")
        projected = dict(request)
        if operator_response is not None:
            projected["operator_response"] = dict(operator_response)
        await asyncio.to_thread(reply, self._session.session_id, projected,
                                "decline" if decision == "cancel" else decision)

    async def events(self) -> AsyncIterator[RuntimeEvent]:
        if hasattr(self._connector, "events_for_session"):
            iterator = self._connector.events_for_session(self._session.session_id)
        else:
            iterator = self._connector.events()
        while True:
            native = await asyncio.to_thread(_next_event, iterator)
            if native is None:
                return
            phase_fn = getattr(self._connector, "delivery_event_phase", None)
            outcome_fn = getattr(self._connector, "delivery_outcome", None)
            phase = native.delivery_phase or (phase_fn(native) if phase_fn else None)
            outcome = native.delivery_outcome or (outcome_fn(native) if outcome_fn else None)
            if (native.harness_kind == "pi" and native.native_event == "agent_start" and
                    phase == "started" and self._active_operation_id is not None):
                self._pi_started_for_active = True
            if native.kind == "turn_started":
                if native.harness_kind == "codex" and (
                        self._active_operation_id is None or
                        type(native.turn_id) is not str or not native.turn_id or
                        native.turn_id in self._recent_codex_turn_set or
                        (self._active_turn_id is not None and
                         self._active_turn_id != native.turn_id)):
                    raise CoreError("EVENT_OPERATION_MISMATCH", "native_pump",
                                    possible_effect=True)
                if native.turn_id is not None:
                    self._active_turn_id = native.turn_id
            if phase == "terminal" and native.kind == "turn_completed":
                active = self._active_operation_id
                if (native.harness_kind == "pi" and native.native_event == "agent_settled" and
                        (active is None or not self._pi_started_for_active)):
                    raise CoreError("EVENT_OPERATION_MISMATCH", "native_pump",
                                    possible_effect=True)
                if native.harness_kind == "codex" and (
                        active is None or type(native.turn_id) is not str or
                        not native.turn_id or
                        native.turn_id != self._active_turn_id):
                    raise CoreError("EVENT_OPERATION_MISMATCH", "native_pump",
                                    possible_effect=True)
                if active is not None and native.operation_id not in (None, active):
                    raise CoreError("EVENT_OPERATION_MISMATCH", "native_pump",
                                    possible_effect=True)
                if outcome in {"success", "failed", "interrupted"}:
                    self._last_outcome = outcome
                native = replace(native, operation_id=active,
                                 delivery_phase="terminal",
                                 delivery_outcome=outcome or self._last_outcome)
                if native.harness_kind == "codex":
                    self._remember_codex_turn(native.turn_id)
                self._active_operation_id = None
                self._active_turn_id = None
                self._pi_started_for_active = False
                self._last_outcome = None
            elif outcome in {"success", "failed", "interrupted"}:
                self._last_outcome = outcome
            yield translate_native_event(self._redactor.scrub(native),
                                         server_id=self._context.server_id,
                                         executor_id=self._context.executor_id,
                                         session_id=self._session_id,
                                         stream_epoch=self._epoch,
                                         native_session_id=self._session.session_id)

    async def close(self) -> str:
        if self._closed:
            return "already_closed"
        self._close_started = True
        if not self._end_attempted:
            self._end_attempted = True
            try:
                await asyncio.to_thread(self._connector.send, self._session,
                                        HarnessCommand(self._session.session_id, "end"))
                self._end_sent = True
            except Exception:
                pass
        try:
            before_close = await asyncio.to_thread(self._connector.observe_lifecycle,
                                                   self._session)
        except Exception:
            before_close = {}
        await asyncio.to_thread(self._connector.close)
        try:
            after_close = await asyncio.to_thread(self._connector.observe_lifecycle,
                                                  self._session)
        except Exception:
            after_close = {}
        self._closed = after_close.get("stop_observed") is True
        # A tree that stopped only because close() enforced containment did
        # not demonstrate graceful native shutdown.
        return ("graceful" if self._closed and self._end_sent and
                before_close.get("stop_observed") is True else "unknown")

    async def force_stop(self) -> None:
        """Request owned-tree containment independently of a stuck send."""
        self._close_started = True
        await asyncio.to_thread(self._connector.force_stop)

    async def observe(self) -> tuple[str, str]:
        lifecycle = await asyncio.to_thread(self._connector.observe_lifecycle,
                                            self._session)
        state = "STOPPED" if lifecycle.get("stop_observed") is True else "RUNNING"
        if state == "STOPPED":
            self._closed = True
            self._close_started = True
        return state, "UNKNOWN"


class CopiedAdapterFactory:
    """Real launch gate; copied protocols require Core-owned qualification.

    Synthetic peer tests use injected NativeFactory instances; they do not
    grant a real installation capability. The current Core allowlist is empty.
    """

    def __init__(self, environment: Callable[[PreparedLaunch],
                                             Awaitable[Mapping[str, str]]],
                 *, pi_native_action: Callable[[PreparedLaunch, str, ExecutionContext],
                                              Awaitable[PiNativeActionLaunch | None]] | None = None,
                 codex_client_info: Mapping[str, str] | None = None,
                 codex_resume: Callable[[PreparedLaunch, str, ExecutionContext],
                                        Awaitable[CodexResumeGrant | None]] | None = None,
                 native_approvals_enabled: bool = False):
        if type(native_approvals_enabled) is not bool:
            raise ValueError("native_approvals_enabled must be bool")
        self._environment = environment
        self._pi_native_action = pi_native_action
        self._codex_client_info = (dict(codex_client_info)
                                   if codex_client_info is not None else None)
        self._codex_resume = codex_resume
        self._native_approvals_enabled = native_approvals_enabled

    async def open(self, prepared: PreparedLaunch, session_id: str,
                   context: ExecutionContext, *, stream_epoch: str) -> CopiedAdapterSession:
        spec = adapter_spec(prepared.intent.adapter_id)
        if spec.mode != "managed":
            raise CoreError("CAPABILITY_UNSUPPORTED", "open", retry_safe=True)
        # PC11: refuse productive work before secrets/spawn when the host's
        # containment backend cannot honor its contract. Never a silent
        # fallback to bare kill(pid).
        from .process import require_containment
        require_containment()
        kind = spec.native_kind
        if not qualified_build(
                kind, prepared.candidate.version, sys.platform,
                prepared.candidate.architecture, prepared.candidate.fingerprint,
                build_identity=prepared.candidate.build_identity):
            raise CoreError("NATIVE_VERSION_UNQUALIFIED", "open", retry_safe=True)
        if (self._native_approvals_enabled and
                not {"approval.decide", "input.provide"}.issubset(
                    context.allowed_actions)):
            raise CoreError("BINDING_NOT_AUTHORIZED", "native_approval_launch",
                            retry_safe=True)
        env = dict(await self._environment(prepared))
        allowed_mcp_names = {_token_env_name(reference)
                             for reference in prepared.secret_refs
                             if isinstance(reference, str) and
                             reference.startswith("mcp-cap:")}
        for name, value in env.items():
            if name.startswith("NEXUS_MCP_TOKEN_"):
                if (name not in allowed_mcp_names or not isinstance(value, str) or
                        not value or "nxs_" in value or "nxsept_" in value):
                    raise CoreError("BINDING_NOT_AUTHORIZED", "environment",
                                    retry_safe=True)
            elif "NEXUS" in name.upper():
                raise CoreError("BINDING_NOT_AUTHORIZED", "environment",
                                retry_safe=True)
        native_action = None
        resume_grant = None
        if kind == "codex":
            resume_grant = (await self._codex_resume(prepared, session_id, context)
                            if self._codex_resume is not None else None)
            if resume_grant is not None and (
                    type(resume_grant) is not CodexResumeGrant or
                    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}",
                                     resume_grant.thread_id) or
                    resume_grant.session_id != session_id or
                    resume_grant.server_id != context.server_id or
                    resume_grant.executor_id != context.executor_id or
                    resume_grant.binding_id != context.binding_id or
                    resume_grant.agent_id != context.agent_id or
                    resume_grant.workspace_id != context.workspace_id or
                    resume_grant.session_owner_generation != context.session_owner_generation or
                    resume_grant.candidate_fingerprint != prepared.candidate.fingerprint or
                    resume_grant.root_fingerprint != prepared.root_fingerprint or
                    resume_grant.profile_fingerprint != prepared.profile_fingerprint or
                    resume_grant.terminal_observed is not True or
                    resume_grant.persisted_rollout_observed is not True or
                    resume_grant.exclusive_owner is not True):
                raise CoreError("BINDING_NOT_AUTHORIZED", "codex_resume",
                                retry_safe=True)
            client_kwargs = (dict(self._codex_client_info)
                             if self._codex_client_info is not None else {})
            # PC08 (F07): the explicit model reaches the verified native
            # mechanism - thread/start (and thread/resume) accept a nullable
            # ``model`` string in the qualified 0.157.0 contract - instead of
            # disappearing after the profile digest.
            explicit_model = prepared.intent.model
            if explicit_model is not None:
                client_kwargs["thread_start_overrides"] = {
                    "model": explicit_model}
            connector = load_adapter(spec.adapter_id)(command=prepared.argv,
                                                      cwd=prepared.cwd, env=env,
                                                      **client_kwargs)
        elif kind == "pi":
            native_action = (await self._pi_native_action(prepared, session_id, context)
                             if self._pi_native_action is not None else None)
            if native_action is not None and (
                    not isinstance(native_action, PiNativeActionLaunch) or
                    native_action.session_id != session_id or
                    native_action.capability_ref not in prepared.secret_refs):
                raise CoreError("BINDING_NOT_AUTHORIZED", "native_action_launch")
            connector = load_adapter(spec.adapter_id)(command=prepared.argv,
                                                      cwd=prepared.cwd, env=env,
                                                      native_action=native_action)
        else:
            connector = load_adapter(spec.adapter_id)(binary=prepared.argv[0],
                                                      argv=prepared.argv[1:],
                                                      cwd=prepared.cwd, env=env)
        if self._native_approvals_enabled and kind in {"codex", "claude_code"}:
            connector.native_approvals_enabled = True
        secrets = (*credential_values(env),
                   *((native_action.capability_ref,) if native_action is not None else ()))
        redactor = NativeSecretRedactor(secrets)
        try:
            start_kwargs = {"owning_agent_id": context.agent_id}
            if resume_grant is not None:
                start_kwargs["resume_thread_id"] = resume_grant.thread_id
            native_session = await asyncio.to_thread(connector.start,
                                                     **start_kwargs)
        except BaseException:
            await asyncio.to_thread(connector.close)
            raise
        return CopiedAdapterSession(connector, native_session,
                                    session_id=session_id,
                                    stream_epoch=stream_epoch, context=context,
                                    redactor=redactor)
