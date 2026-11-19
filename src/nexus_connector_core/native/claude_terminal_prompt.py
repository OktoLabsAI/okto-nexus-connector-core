"""Local prompt gate for an owned Claude terminal.

The host supplies the decision about the exact admitted operation. The hook
and its bearer identify a native caller, independently of operator authority.
"""

import hashlib
import json
import math
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

from ..identifiers import validate_external_id
from ..models import CoreError, EffectNotSent
from ..protocol import canonical_json, strict_json
from .claude_history_identity import claude_session_uuid
from .native_inputs import CLAUDE_INPUT, response_for, validate_request

_ENV_KEY = "OKTO_CLAUDE_PROMPT_HOOK_TOKEN"
_PATH = "/prompt"
_COMPLETION_PATH = "/completion"
_START_PATH = "/start"
_QUESTION_PATH = "/question"
_START_URL = "OKTO_CLAUDE_TERMINAL_START_URL"
_MAX_PROMPT_BYTES = 64 * 1024
_MAX_REQUEST_BYTES = 448 * 1024
# One MiB of result text can expand to six times that size in JSON.
_MAX_COMPLETION_REQUEST_BYTES = 7 * 1024 * 1024
CLAUDE_PROMPT_HOOK_TIMEOUT = 8
_QUESTION_WAIT = 120
_QUESTION_METHOD = "control_request:can_use_tool"
_QUESTION_DENIAL = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "The question has no current Nexus answer."}}
_STAGE = "claude_terminal_prompt"
_DENIAL = {
    "decision": "block",
    "reason": "This input does not have a current Nexus authorization.",
    "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "suppressOriginalPrompt": True},
}


@dataclass(frozen=True, slots=True)
class _Permit:
    operation_id: str
    digest: bytes
    deadline: float
    check: object
    delivery: "_PromptDelivery"


@dataclass(frozen=True, slots=True)
class ClaudeTerminalResult:
    operation_id: str
    output_text: str | None
    failure_code: str | None
    interrupted: bool = False


@dataclass(frozen=True, slots=True)
class _AuthorizedPrompt:
    prompt_id: str
    permit: _Permit
    admitted_ms: int


@dataclass(frozen=True, slots=True)
class _CompletionCandidate:
    result: ClaudeTerminalResult
    earliest_idle_ms: int
    output_sha256: str | None


@dataclass(slots=True)
class _PendingQuestion:
    prompt: _AuthorizedPrompt
    request: dict
    deadline: float
    ready: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    published: bool = False
    reply: dict | None = None
    check: Callable[[str], None] | None = None
    refusal: EffectNotSent | None = None
    written: bool = False


class _QuestionHookServer(ThreadingHTTPServer):
    def __init__(self, address, handler):
        self._slots = threading.BoundedSemaphore(4)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._slots.release()


class _PromptDelivery:
    def __init__(self):
        self._done = threading.Event()
        self._allowed = False

    def complete(self, allowed):
        self._allowed = allowed
        self._done.set()

    def wait(self, timeout):
        return self._done.wait(timeout) and self._allowed


class ClaudeTerminalPromptGate:
    """Permit one exact prompt from the prepared session at a time.

    `authorize` must mark possible delivery for that operation under current
    host authority before returning True. An error or lost reply leaves the
    permit spent. Reconciliation belongs to the host journal.
    """

    def __init__(self, session_uuid, cwd, permission_mode, authorize, *, observe_results=False, startup=None,
                 allow_questions=False):
        if (claude_session_uuid(session_uuid) is None or type(cwd) is not str or not Path(cwd).is_absolute()
                or type(permission_mode) is not str or not permission_mode or not callable(authorize)
                or type(observe_results) is not bool or type(allow_questions) is not bool
                or (allow_questions and (not observe_results or startup is None))):
            raise ValueError("Invalid Claude prompt gate scope.")
        self._session_uuid = session_uuid
        self._cwd = Path(cwd)
        self._permission_mode = permission_mode
        self._authorize = authorize
        self._secret = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._used = set()
        self._permit = None
        self._observe_results = observe_results
        self._pending_result = None
        self._candidate = None
        self._prompt_ids = set()
        self._closed = False
        self._server = None
        self._startup = startup
        self._allow_questions = allow_questions
        self._question = None
        self._question_tools = set()
        self.startup_confirmed = threading.Event()

    def __enter__(self):
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(2)
                super().setup()

            def log_message(self, *_args):
                pass

            def do_POST(self):
                status, body, delivery = gate._request(self)
                written = False
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    data = json.dumps(body, separators=(",", ":")).encode("ascii")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    self.wfile.flush()
                    written = True
                except OSError:
                    pass
                finally:
                    if isinstance(delivery, _PendingQuestion):
                        gate._complete_question(delivery, written)
                    elif delivery is not None:
                        delivery.complete(written and status == 200 and body == {})

        with self._lock:
            if self._server is not None or self._closed:
                raise CoreError("SESSION_CONFLICT", _STAGE)
            server_type = _QuestionHookServer if self._allow_questions else HTTPServer
            server = server_type(("127.0.0.1", 0), Handler)
            self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            try:
                self._thread.start()
            except BaseException:
                server.server_close()
                raise
            self._server = server
        return self

    def __exit__(self, *_exc):
        with self._lock:
            self._closed = True
            self._permit = None
            self._pending_result = None
            self._candidate = None
            if self._question is not None:
                self._question.ready.set()
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
            self._thread.join()

    def launch_settings(self):
        """Return the restricted hook settings and a separate child-only environment entry."""
        with self._lock:
            if self._server is None:
                raise CoreError("NATIVE_UNAVAILABLE", _STAGE)
            port = self._server.server_port
        hook = {"type": "http", "timeout": 4, "headers": {"Authorization": "Bearer $" + _ENV_KEY},
                "allowedEnvVars": [_ENV_KEY]}
        root = f"http://127.0.0.1:{port}"
        hooks = {"UserPromptSubmit": [{"hooks": [dict(
            hook, url=root + _PATH, timeout=CLAUDE_PROMPT_HOOK_TIMEOUT, onFailure="block")]}]}
        if self._observe_results:
            for name in ("Stop", "StopFailure"):
                hooks[name] = [{"hooks": [dict(hook, url=root + _COMPLETION_PATH)]}]
        if self._allow_questions:
            hooks["PreToolUse"] = [{"matcher": "^AskUserQuestion$", "hooks": [
                dict(hook, url=root + _QUESTION_PATH, timeout=_QUESTION_WAIT + 5, onFailure="block"),
            ]}]
        environment = {_ENV_KEY: self._secret}
        if self._startup is not None:
            powershell, _ = self._startup
            # Fixed executable and script. Neither the history path nor a
            # credential enters the command or the command's argument list.
            script = (
                "$ErrorActionPreference='Stop'; "
                "$payload=[Console]::In.ReadToEnd(); "
                f"$header=@{{Authorization=('Bearer '+$env:{_ENV_KEY})}}; "
                f"Invoke-WebRequest -UseBasicParsing -Method Post -Uri $env:{_START_URL} "
                "-Headers $header -ContentType 'application/json' -Body $payload -TimeoutSec 3 | Out-Null"
            )
            hooks["SessionStart"] = [{"matcher": "resume", "hooks": [{
                "type": "command", "command": powershell,
                "args": ["-NoProfile", "-NonInteractive", "-Command", script], "timeout": 5,
            }]}]
            environment[_START_URL] = root + _START_PATH
        return {"hooks": hooks}, environment

    def arm(self, operation_id, text, *, ttl=10, check=None):
        validate_external_id(operation_id, stage=_STAGE)
        digest = _prompt_digest(text)
        if (digest is None or type(ttl) not in (int, float) or not 0 < ttl <= 30 or not math.isfinite(ttl)
                or (check is not None and not callable(check))):
            raise CoreError("VALIDATION_ERROR", _STAGE)
        with self._lock:
            now = time.monotonic()
            if (self._server is None or (self._startup is not None and not self.startup_confirmed.is_set())
                    or operation_id in self._used or self._pending_result is not None
                    or (self._permit is not None and self._permit.deadline > now)):
                raise CoreError("SESSION_CONFLICT", _STAGE)
            self._used.add(operation_id)
            delivery = _PromptDelivery()
            self._permit = _Permit(operation_id, digest, now + ttl, check, delivery)
            return delivery

    def discard(self, operation_id):
        """Retire an unconsumed permit when the effect waiter gives up."""
        with self._lock:
            if self._permit is not None and self._permit.operation_id == operation_id:
                self._permit.delivery.complete(False)
                self._permit = None

    def _request(self, handler):
        completion = self._observe_results and handler.path == _COMPLETION_PATH
        startup = self._startup is not None and handler.path == _START_PATH
        question = self._allow_questions and handler.path == _QUESTION_PATH
        if handler.path != _PATH and not completion and not startup and not question:
            return 404, {}, None
        token = handler.headers.get_all("Authorization", [])
        if (len(token) != 1 or not token[0].isascii()
                or not secrets.compare_digest(token[0], "Bearer " + self._secret)):
            return 403, {}, None
        length = handler.headers.get_all("Content-Length", [])
        limit = _MAX_COMPLETION_REQUEST_BYTES if completion else _MAX_REQUEST_BYTES
        if (len(length) != 1 or not re.fullmatch(r"[0-9]{1,7}", length[0])
                or not 0 < int(length[0]) <= limit or handler.headers.get("Transfer-Encoding")
                or handler.headers.get_content_type() != "application/json"):
            return 400, {}, None
        try:
            data = handler.rfile.read(int(length[0]))
            payload = strict_json(data.decode("utf-8"))
        except (OSError, ValueError, RecursionError):
            return 400, {}, None
        if len(data) != int(length[0]) or type(payload) is not dict:
            return 400, {}, None
        if completion:
            return self._receive_completion(payload), {}, None
        if question:
            return self._receive_question(payload)
        if startup:
            _, path = self._startup
            if (payload.get("hook_event_name") == "SessionStart" and payload.get("source") == "resume"
                    and payload.get("session_id") == self._session_uuid
                    and type(payload.get("cwd")) is str and Path(payload["cwd"]) == self._cwd
                    and type(payload.get("transcript_path")) is str and Path(payload["transcript_path"]) == path):
                self.startup_confirmed.set()
                return 200, {}, None
            return 409, {}, None
        if (payload.get("hook_event_name") != "UserPromptSubmit"
                or payload.get("session_id") != self._session_uuid
                or payload.get("permission_mode") != self._permission_mode
                or type(payload.get("cwd")) is not str or Path(payload["cwd"]) != self._cwd):
            return 200, _DENIAL, None
        digest = _prompt_digest(payload.get("prompt"))
        prompt_id = payload.get("prompt_id")
        with self._lock:
            permit = self._permit
            if (self._closed or permit is None or permit.deadline <= time.monotonic()
                    or digest is None or not secrets.compare_digest(permit.digest, digest)):
                return 200, _DENIAL, None
            if self._observe_results and (
                    not _valid_prompt_id(prompt_id) or prompt_id in self._prompt_ids):
                return 200, _DENIAL, None
            self._permit = None
            try:
                allowed = self._authorize(permit.operation_id) is True
                if allowed and permit.check is not None:
                    allowed = permit.check() is True
            except Exception:
                return 503, {}, permit.delivery
            if not allowed or permit.deadline <= time.monotonic():
                return 200, _DENIAL, permit.delivery
            if self._observe_results:
                self._prompt_ids.add(prompt_id)
                # Keep correlation even if the response socket fails after a partial write.
                self._pending_result = _AuthorizedPrompt(prompt_id, permit, time.time_ns() // 1_000_000)
            return 200, {}, permit.delivery

    def _receive_question(self, payload):
        source = payload.get("tool_input")
        tool_id = payload.get("tool_use_id")
        if (payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") != "AskUserQuestion"
                or payload.get("session_id") != self._session_uuid or payload.get("permission_mode") != self._permission_mode
                or "agent_id" in payload or type(payload.get("cwd")) is not str or Path(payload["cwd"]) != self._cwd
                or type(payload.get("transcript_path")) is not str
                or Path(payload["transcript_path"]) != self._startup[1]
                or not _valid_prompt_id(tool_id) or type(source) is not dict or set(source) != {"questions"}):
            return 200, _QUESTION_DENIAL, None
        params = {"tool_name": "AskUserQuestion", "tool_use_id": tool_id, "input": source}
        try:
            validate_request(CLAUDE_INPUT, params)
            request = {"schema_version": 1, "request_id": "claude_question_" + secrets.token_hex(16),
                "request_hash": hashlib.sha256(canonical_json(params)).hexdigest(),
                "method": _QUESTION_METHOD, "params": params, "local_generation": 1}
            if len(canonical_json(request)) > 16384:
                raise ValueError("Oversized question.")
        except (ValueError, TypeError, OverflowError, RecursionError):
            return 200, _QUESTION_DENIAL, None
        with self._lock:
            pending = self._pending_result
            if (self._closed or pending is None or self._candidate is not None
                    or payload.get("prompt_id") != pending.prompt_id or self._question is not None
                    or len(self._question_tools) >= 128 or tool_id in self._question_tools):
                return 200, _QUESTION_DENIAL, None
            self._question_tools.add(tool_id)
            question = self._question = _PendingQuestion(pending, request, time.monotonic() + _QUESTION_WAIT)
        question.ready.wait(max(0, question.deadline - time.monotonic()))
        try:
            if question.check is not None:
                question.check(question.prompt.permit.operation_id)
            with self._lock:
                if (self._closed or question.reply is None or question.prompt is not self._pending_result
                        or self._candidate is not None or time.monotonic() >= question.deadline):
                    raise EffectNotSent("The Claude question is no longer waiting.", code="NATIVE_REQUEST_NOT_OBSERVED")
            return 200, question.reply, question
        except EffectNotSent as error:
            question.refusal = error
            return 200, _QUESTION_DENIAL, question
        except Exception:
            question.refusal = EffectNotSent("The active Claude question could not be revalidated.",
                                             code="BINDING_NOT_AUTHORIZED")
            return 200, _QUESTION_DENIAL, question

    def _complete_question(self, question, written):
        with self._lock:
            if self._question is question:
                self._question = None
            question.written = written
            question.finished.set()

    def take_question(self):
        with self._lock:
            question = self._question
            if (question is None or question.published or question.ready.is_set() or self._candidate is not None
                    or question.prompt is not self._pending_result or time.monotonic() >= question.deadline):
                return None
            question.published = True
            return question.prompt.permit.operation_id, question.request

    def reply_question(self, request, decision, response, check):
        with self._lock:
            question = self._question
            if (self._closed or question is None or not question.published or question.ready.is_set()
                    or question.prompt is not self._pending_result or time.monotonic() >= question.deadline
                    or any(request.get(key) != question.request[key] for key in (
                        "request_id", "request_hash", "method", "params", "local_generation"))):
                raise EffectNotSent("The Claude question is no longer waiting.", code="NATIVE_REQUEST_NOT_OBSERVED")
            try:
                answer = response_for(question.request, response, approved=decision == "accept")
            except (ValueError, TypeError, OverflowError, RecursionError):
                raise EffectNotSent("The Claude question needs a matching answer.", code="VALIDATION_ERROR") from None
            if answer is None:
                question.reply = _QUESTION_DENIAL
            else:
                answers = {prompt: ", ".join(value) if isinstance(value, list) else value
                           for prompt, value in answer["answers"].items()}
                question.reply = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": {**question.request["params"]["input"], "answers": answers},
                }}
            question.check = check
            question.ready.set()
        if not question.finished.wait(max(0, question.deadline - time.monotonic()) + 3):
            raise CoreError("OUTCOME_UNKNOWN", _STAGE, possible_effect=True)
        if question.refusal is not None:
            raise question.refusal
        if not question.written:
            raise CoreError("OUTCOME_UNKNOWN", _STAGE, possible_effect=True)

    def _receive_completion(self, payload):
        with self._lock:
            pending = self._pending_result
            if (self._closed or pending is None or payload.get("prompt_id") != pending.prompt_id
                    or payload.get("session_id") != self._session_uuid
                    or type(payload.get("cwd")) is not str or Path(payload["cwd"]) != self._cwd):
                return 200
            kind = payload.get("hook_event_name")
            if kind == "Stop":
                self._candidate = None
                output = payload.get("last_assistant_message")
                if (payload.get("permission_mode") != self._permission_mode
                        or type(payload.get("stop_hook_active")) is not bool
                        or payload.get("background_tasks") != [] or payload.get("session_crons") != []
                        or type(output) is not str):
                    return 200
                try:
                    output_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
                except UnicodeError:
                    return 200
                output = output.replace(self._secret, "[REDACTED]")
                result = ClaudeTerminalResult(pending.permit.operation_id, output, None)
                # Another Stop hook may continue this prompt. Require both a
                # new idle state and the native transcript's matching end.
                earliest_idle_ms = time.time_ns() // 1_000_000
            elif kind == "StopFailure":
                self._candidate = None
                if ("permission_mode" in payload and payload["permission_mode"] != self._permission_mode
                        or type(payload.get("error")) is not str or not payload["error"]):
                    return 200
                code = ("PROVIDER_AUTH_REQUIRED" if payload["error"] == "authentication_failed"
                        else "NATIVE_OPERATION_FAILED")
                result = ClaudeTerminalResult(pending.permit.operation_id, None, code)
                output_sha256 = None
                # The CLI can enter idle before delivering StopFailure.
                earliest_idle_ms = pending.admitted_ms
            else:
                return 200
            self._candidate = _CompletionCandidate(result, earliest_idle_ms, output_sha256)
            return 200

    def take_finished_result(self, observe_finished, observe_interrupted=None):
        """Consume the latest correlated result with an exact native completion observation."""
        with self._lock:
            candidate = self._candidate
            pending = self._pending_result
        if pending is None:
            return None
        result = None
        if candidate is not None:
            idle_since = observe_finished(candidate.output_sha256)
            if type(idle_since) is int and candidate.earliest_idle_ms < idle_since <= time.time_ns() // 1_000_000:
                result = candidate.result
        if result is None and observe_interrupted is not None:
            ended = observe_interrupted(pending.prompt_id, pending.permit.digest, pending.admitted_ms)
            if type(ended) is int and pending.admitted_ms < ended <= time.time_ns() // 1_000_000:
                result = ClaudeTerminalResult(pending.permit.operation_id, None, None, interrupted=True)
        if result is None:
            return None
        with self._lock:
            if pending is not self._pending_result or candidate is not self._candidate:
                return None
            self._candidate = None
            self._pending_result = None
            self._question_tools.clear()
            if self._question is not None:
                self._question.ready.set()
            return result

    def read_generation(self, observe, *, skip_operation=None):
        """Bind current native generation to the authenticated pending prompt."""
        with self._lock:
            pending = self._pending_result
            if (pending is None or self._candidate is not None or self._question is not None
                    or pending.permit.operation_id == skip_operation):
                return None
        evidence = observe(pending.prompt_id, pending.permit.digest, pending.admitted_ms)
        with self._lock:
            if (evidence is None or pending is not self._pending_result or self._candidate is not None
                    or self._question is not None):
                return None
            return pending.permit.operation_id, evidence


def _valid_prompt_id(value):
    return type(value) is str and 1 <= len(value) <= 160 and value.isascii() and value.isprintable()


def _prompt_digest(text):
    if type(text) is not str or not text or len(text) > _MAX_PROMPT_BYTES:
        return None
    try:
        data = text.encode("utf-8")
    except UnicodeError:
        return None
    if len(data) > _MAX_PROMPT_BYTES:
        return None
    return hashlib.sha256(data).digest()
