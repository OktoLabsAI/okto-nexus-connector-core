"""Observe main-thread generation on the reviewed Claude terminal build."""

import hashlib
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from ..protocol import strict_json
from ..session_mcp_file import _protect_windows
from .claude_history_identity import claude_session_uuid
from .claude_terminal_owner import _REVIEWED_VERSION, _transcript_tail, observe_claude_terminal_status

_TAIL_BYTES = 128 * 1024
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MILLISECOND = timedelta(milliseconds=1)
_PREFIX = re.compile(rb"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z) \[DEBUG\] (.*)$")
_ENGINE_START = re.compile(rb"\[engine\] turn [0-9]+ start")
_ENGINE_FINISH = re.compile(rb"\[engine\] turn [0-9]+ (?:end|finish|done|abort).*")
_FIRST_BYTE = re.compile(rb"\[API:timing\] first byte after [0-9]+ms")
_MAIN_REQUEST = b"[API REQUEST] /v1/messages source=repl_main_thread"
_HEX = re.compile(r"[0-9a-f]{64}")


class ClaudeGenerationTrace:
    """Hold a private diagnostic file for the native process's lifetime."""

    def __init__(self):
        self._lock = Lock()
        self._directory = Path(tempfile.mkdtemp(prefix="okto-claude-trace-"))
        self._file = None
        self.path = self._directory / "stream.log"
        try:
            _protect_windows(self._directory)
            fd = os.open(self.path, os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY | os.O_TEMPORARY)
            try:
                self._file = os.fdopen(fd, "rb")
            except BaseException:
                os.close(fd)
                raise
        except BaseException:
            self.close()
            raise

    def arguments(self):
        return "--debug=api:timing,api request,engine", "--debug-file", str(self.path)

    def read_tail(self):
        with self._lock:
            if self._file is None:
                return b""
            size = os.fstat(self._file.fileno()).st_size
            start = max(0, size - _TAIL_BYTES)
            self._file.seek(start)
            data = self._file.read(size - start)
            if len(data) != size - start or not data.endswith(b"\n"):
                return b""
            return data.split(b"\n", 1)[1] if start else data

    def close(self):
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
            # Claude adds a link named 'latest' alongside the selected log.
            (self._directory / "latest").unlink(missing_ok=True)
            if self._directory.exists():
                self._directory.rmdir()


def observe_claude_generation(terminal, history, birth, trace, prompt_id, digest, admitted_ms):
    """Return a private revision only while one exact main request is observable."""
    busy_at = observe_claude_terminal_status(terminal, history, birth, "busy")
    if busy_at is None:
        return None
    try:
        started = _stream_started_at(trace.read_tail(), admitted_ms)
        if started is None or not busy_at <= started <= time.time_ns() // 1_000_000:
            return None
        records = _transcript_tail(history)
        request = _request_for_prompt(records, history, prompt_id, digest) if records is not None else None
        if request is None or _stream_started_at(trace.read_tail(), admitted_ms) != started:
            return None
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        return None
    if observe_claude_terminal_status(terminal, history, birth, "busy") != busy_at:
        return None
    return request, started


def _stream_started_at(tail, admitted_ms):
    stage = 0
    last_at = admitted_ms
    first_byte = None
    for line in tail.splitlines():
        match = _PREFIX.fullmatch(line)
        if match is None:
            continue
        raw_time, event = match.groups()
        millis = (datetime.fromisoformat(raw_time.decode("ascii")) - _EPOCH) // _MILLISECOND
        if millis < admitted_ms:
            continue
        if millis < last_at:
            return None
        last_at = millis
        if _ENGINE_START.fullmatch(event):
            if stage:
                return None
            stage = 1
        elif event.startswith(b"[API REQUEST]"):
            if stage != 1 or event != _MAIN_REQUEST:
                return None
            stage = 2
        elif _FIRST_BYTE.fullmatch(event):
            if stage != 2:
                return None
            stage = 3
            first_byte = millis
        elif _ENGINE_FINISH.fullmatch(event):
            return None
    return first_byte


def _request_for_prompt(records, history, prompt_id, digest):
    request_id = None
    message_hashes = ()
    matched_body = False
    for line in records:
        record = strict_json(line.decode("utf-8"))
        if type(record) is not dict:
            return None
        kind = record.get("type")
        if kind == "api-request":
            if (request_id is not None or record.get("sessionId") != history.session_uuid
                    or record.get("querySource") != "repl_main_thread" or record.get("version") != _REVIEWED_VERSION):
                return None
            request_id = claude_session_uuid(record.get("id"))
            message_hashes = record.get("tail")
            if (request_id is None or type(message_hashes) is not list or not message_hashes
                    or any(type(d) is not str or _HEX.fullmatch(d) is None for d in message_hashes)):
                return None
        elif kind == "api-request-blob" and request_id is not None and record.get("hash") in message_hashes:
            message = record.get("message")
            if record.get("sessionId") != history.session_uuid or type(message) is not dict:
                return None
            content = message.get("content")
            if message.get("role") == "user" and type(content) is list:
                for block in content:
                    if type(block) is dict and block.get("type") == "text" and _same_text(block.get("text"), digest):
                        matched_body = True
        elif kind == "assistant" and record.get("isSidechain") is not True:
            return None
        elif kind == "user" and record.get("isSidechain") is not True:
            message = record.get("message")
            cwd = record.get("cwd")
            if (not matched_body or record.get("promptId") != prompt_id or record.get("isSidechain") is not False
                    or record.get("isMeta") is True or record.get("sessionId") != history.session_uuid
                    or type(cwd) is not str or Path(cwd) != Path(history.workspace)
                    or record.get("version") != _REVIEWED_VERSION or record.get("entrypoint") != "cli"
                    or record.get("permissionMode") != "plan" or record.get("promptSource") != "typed"
                    or type(message) is not dict or message.get("role") != "user"
                    or not _same_text(message.get("content"), digest)):
                return None
            return request_id
    return None


def _same_text(text, digest):
    return type(text) is str and hashlib.sha256(text.encode("utf-8")).digest() == digest
