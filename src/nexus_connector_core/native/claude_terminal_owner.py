"""Verify a saved Claude conversation against the exact owned Windows terminal."""

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import ProcessBirthEvidence
from ..protocol import strict_json
from .claude_history_identity import claude_session_uuid
from .claude_saved_history import ClaudeSavedHistory, claude_history_path
from .saved_history_file import file_identity, file_version, plain_path

_REVIEWED_VERSION = "2.1.328"
_MAX_REGISTRY_BYTES = 64 * 1024
_MAX_TRANSCRIPT_TAIL = 8 * 1024 * 1024
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MILLISECOND = timedelta(milliseconds=1)


def observe_claude_terminal_owner(
    terminal, history: ClaudeSavedHistory, birth: ProcessBirthEvidence,
) -> bool:
    """Corroborate the adopted UUID using the held handle and Claude's local registry.

    Call after launching the reviewed build and before enabling any input.
    This observation does not decide whether the source is retired, whether
    the effective settings are approved, or whether a launch is authorized.
    """
    return observe_claude_terminal_idle_since(terminal, history, birth) is not None


def observe_claude_terminal_idle_since(
    terminal, history: ClaudeSavedHistory, birth: ProcessBirthEvidence,
) -> int | None:
    """Return the native idle transition timestamp on the current owned process."""
    if (birth.platform != "win32" or birth.containment != "windows_job"
            or type(birth.pid) is not int or birth.pid <= 0
            or not re.fullmatch(r"filetime:[a-f0-9]{16}", birth.birth_token)
            or claude_session_uuid(history.session_uuid) is None):
        return None
    home, workspace = Path(history.state_home), Path(history.workspace)
    if (not home.is_absolute() or not workspace.is_absolute()
            or ".." in home.parts or ".." in workspace.parts):
        return None
    registry = home / "sessions" / f"{birth.pid}.json"
    try:
        if terminal.poll() is not None or terminal.birth != birth:
            return None
        original = _registry_version(registry, home, workspace, history)
        if not 0 < original[2] <= _MAX_REGISTRY_BYTES:
            return None
        with registry.open("rb") as stream:
            opened = file_version(os.fstat(stream.fileno()))
            if opened[:4] != original[:4]:
                return None
            body = stream.read(_MAX_REGISTRY_BYTES + 1)
            if len(body) != original[2] or file_version(os.fstat(stream.fileno())) != opened:
                return None
        record = strict_json(body.decode("utf-8"))
        if type(record) is not dict:
            return None
        cwd = record.get("cwd")
        idle_since = record.get("statusUpdatedAt")
        if (
            type(record.get("pid")) is int and record["pid"] == birth.pid
            and record.get("procStart") == str(int(birth.birth_token.removeprefix("filetime:"), 16))
            and record.get("sessionId") == history.session_uuid
            and type(cwd) is str and Path(cwd) == workspace
            and record.get("version") == _REVIEWED_VERSION
            and record.get("kind") == "interactive" and record.get("entrypoint") == "cli"
            and record.get("status") == "idle"
            and type(idle_since) is int and idle_since > 0
            and _registry_version(registry, home, workspace, history) == original
            and terminal.birth == birth and terminal.poll() is None
        ):
            return idle_since
    except (OSError, ValueError, TypeError, RecursionError):
        return None
    return None


def _registry_version(registry, home, workspace, history):
    for parent in registry.parents:
        plain_path(parent, directory=True)
    if (file_identity(plain_path(home, directory=True)) != history.home_identity
            or file_identity(plain_path(workspace, directory=True)) != history.workspace_identity):
        raise ValueError("The saved Claude state or workspace directory changed.")
    return file_version(plain_path(registry, directory=False))


def observe_claude_finished_turn(terminal, history, birth, output_sha256):
    """Corroborate success with a flushed turn end and matching transcript text."""
    idle_since = observe_claude_terminal_idle_since(terminal, history, birth)
    if idle_since is None or output_sha256 is None:
        return idle_since
    completed_at = _matching_turn_end(history, output_sha256)
    if (completed_at is None
            or observe_claude_terminal_idle_since(terminal, history, birth) != idle_since):
        return None
    return min(idle_since, completed_at)


def observe_claude_interrupted_turn(terminal, history, birth, prompt_id, prompt_digest, admitted_ms):
    """Corroborate a native cancellation of the exact authorized prompt."""
    idle_since = observe_claude_terminal_idle_since(terminal, history, birth)
    if idle_since is None or idle_since <= admitted_ms:
        return None
    try:
        lines = _transcript_tail(history)
        ended = _read_interrupted_turn(lines, history, prompt_id, prompt_digest) if lines is not None else None
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        return None
    if (ended is None or ended <= admitted_ms
            or observe_claude_terminal_idle_since(terminal, history, birth) != idle_since):
        return None
    return min(ended, idle_since)


def _matching_turn_end(history, output_sha256):
    try:
        lines = _transcript_tail(history)
        return _read_turn_end(lines, history, output_sha256) if lines is not None else None
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        return None


def _transcript_tail(history):
    path = claude_history_path(history.state_home, history.session_uuid, history.workspace)
    if path is None:
        return None
    for parent in path.parents:
        plain_path(parent, directory=True)
    original = file_version(plain_path(path, directory=False))
    if original[:2] != history.file_identity or original[2] <= history.byte_size:
        return None
    start = max(history.byte_size, original[2] - _MAX_TRANSCRIPT_TAIL)
    with path.open("rb") as stream:
        opened = file_version(os.fstat(stream.fileno()))
        if opened[:4] != original[:4]:
            return None
        stream.seek(start)
        tail = stream.read(_MAX_TRANSCRIPT_TAIL + 1)
        if (len(tail) != original[2] - start or not tail.endswith(b"\n")
                or file_version(os.fstat(stream.fileno())) != opened):
            return None
    if file_version(plain_path(path, directory=False)) != original:
        return None
    lines = tail.split(b"\n")
    return reversed(lines[1 if start > history.byte_size else 0:-1])


def _read_interrupted_turn(lines, history, prompt_id, prompt_digest):
    marker = None
    observed_abort = False
    for line in lines:
        record = strict_json(line.decode("utf-8"))
        if type(record) is not dict:
            return None
        kind = record.get("type")
        if record.get("isSidechain") is not False or kind not in {"user", "assistant"}:
            continue
        cwd = record.get("cwd")
        if (record.get("sessionId") != history.session_uuid or type(cwd) is not str
                or Path(cwd) != Path(history.workspace) or record.get("version") != _REVIEWED_VERSION
                or record.get("entrypoint") != "cli"):
            return None
        message = record.get("message")
        if type(message) is not dict or message.get("role") != kind:
            return None
        if marker is None:
            if (kind != "user" or record.get("promptId") != prompt_id
                    or record.get("isMeta") is True
                    or type(record.get("interruptedMessageId")) is not str or not record["interruptedMessageId"]
                    or message.get("content") != [{"type": "text", "text": "[Request interrupted by user]"}]):
                return None
            marker = record
        elif not observed_abort:
            if (kind != "assistant" or record.get("isAbortedMidStream") is not True
                    or claude_session_uuid(record.get("uuid")) is None
                    or record["uuid"] != marker.get("parentUuid")
                    or message.get("id") != marker["interruptedMessageId"]):
                return None
            observed_abort = True
        elif kind == "user":
            text = message.get("content")
            timestamp = marker.get("timestamp")
            if (record.get("promptId") != prompt_id or record.get("isMeta") is True
                    or record.get("permissionMode") != "plan" or record.get("promptSource") != "typed"
                    or type(text) is not str or hashlib.sha256(text.encode("utf-8")).digest() != prompt_digest
                    or type(timestamp) is not str or not timestamp.endswith("Z")):
                return None
            return (datetime.fromisoformat(timestamp) - _EPOCH) // _MILLISECOND
    return None


def _read_turn_end(lines, history, output_sha256):
    completed_at = None
    for line in lines:
        record = strict_json(line.decode("utf-8"))
        if type(record) is not dict:
            return None
        kind = record.get("type")
        if record.get("isSidechain") is not False or kind not in {"system", "user", "assistant"}:
            continue
        if kind == "system" and record.get("subtype") != "turn_duration":
            continue
        cwd = record.get("cwd")
        if (record.get("sessionId") != history.session_uuid or type(cwd) is not str
                or Path(cwd) != Path(history.workspace)):
            return None
        if completed_at is None:
            if kind != "system" or record.get("isMeta") is not False:
                return None
            timestamp = record.get("timestamp")
            if type(timestamp) is not str or not timestamp.endswith("Z"):
                return None
            completed_at = (datetime.fromisoformat(timestamp) - _EPOCH) // _MILLISECOND
            continue
        if kind != "assistant" or record.get("isApiErrorMessage") is True:
            return None
        message = record.get("message")
        content = message.get("content") if type(message) is dict and message.get("role") == "assistant" else None
        if type(content) is not list or any(type(block) is not dict for block in content):
            return None
        texts = [block.get("text") for block in content if block.get("type") == "text"]
        if not texts or any(type(value) is not str for value in texts):
            return None
        if hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest() == output_sha256:
            return completed_at
        return None
    return None
