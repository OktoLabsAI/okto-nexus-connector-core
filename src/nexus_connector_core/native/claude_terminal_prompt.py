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
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ..identifiers import validate_external_id
from ..models import CoreError
from ..protocol import strict_json
from .claude_history_identity import claude_session_uuid

_ENV_KEY = "OKTO_CLAUDE_PROMPT_HOOK_TOKEN"
_PATH = "/prompt"
_MAX_PROMPT_BYTES = 64 * 1024
_MAX_REQUEST_BYTES = 448 * 1024
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

    def __init__(self, session_uuid, cwd, permission_mode, authorize):
        if (claude_session_uuid(session_uuid) is None or type(cwd) is not str or not Path(cwd).is_absolute()
                or type(permission_mode) is not str or not permission_mode or not callable(authorize)):
            raise ValueError("Invalid Claude prompt gate scope.")
        self._session_uuid = session_uuid
        self._cwd = Path(cwd)
        self._permission_mode = permission_mode
        self._authorize = authorize
        self._secret = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._used = set()
        self._permit = None
        self._closed = False
        self._server = None

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
                    if delivery is not None:
                        delivery.complete(written and status == 200 and body == {})

        with self._lock:
            if self._server is not None or self._closed:
                raise CoreError("SESSION_CONFLICT", _STAGE)
            server = HTTPServer(("127.0.0.1", 0), Handler)
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
        return {
            "hooks": {"UserPromptSubmit": [{"hooks": [{
                "type": "http", "url": f"http://127.0.0.1:{port}{_PATH}",
                "timeout": 4, "onFailure": "block",
                "headers": {"Authorization": "Bearer $" + _ENV_KEY},
                "allowedEnvVars": [_ENV_KEY],
            }]}]},
        }, {_ENV_KEY: self._secret}

    def arm(self, operation_id, text, *, ttl=10, check=None):
        validate_external_id(operation_id, stage=_STAGE)
        digest = _prompt_digest(text)
        if (digest is None or type(ttl) not in (int, float) or not 0 < ttl <= 30 or not math.isfinite(ttl)
                or (check is not None and not callable(check))):
            raise CoreError("VALIDATION_ERROR", _STAGE)
        with self._lock:
            now = time.monotonic()
            if (self._server is None or operation_id in self._used
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
        if handler.path != _PATH:
            return 404, {}, None
        token = handler.headers.get_all("Authorization", [])
        if (len(token) != 1 or not token[0].isascii()
                or not secrets.compare_digest(token[0], "Bearer " + self._secret)):
            return 403, {}, None
        length = handler.headers.get_all("Content-Length", [])
        if (len(length) != 1 or not re.fullmatch(r"[0-9]{1,6}", length[0])
                or not 0 < int(length[0]) <= _MAX_REQUEST_BYTES or handler.headers.get("Transfer-Encoding")
                or handler.headers.get_content_type() != "application/json"):
            return 400, {}, None
        try:
            data = handler.rfile.read(int(length[0]))
            payload = strict_json(data.decode("utf-8"))
        except (OSError, ValueError, RecursionError):
            return 400, {}, None
        if (len(data) != int(length[0]) or type(payload) is not dict
                or payload.get("hook_event_name") != "UserPromptSubmit"
                or payload.get("session_id") != self._session_uuid
                or payload.get("permission_mode") != self._permission_mode
                or type(payload.get("cwd")) is not str or Path(payload["cwd"]) != self._cwd):
            return 200, _DENIAL, None
        digest = _prompt_digest(payload.get("prompt"))
        with self._lock:
            permit = self._permit
            if (self._closed or permit is None or permit.deadline <= time.monotonic()
                    or digest is None or not secrets.compare_digest(permit.digest, digest)):
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
            return 200, {}, permit.delivery


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
