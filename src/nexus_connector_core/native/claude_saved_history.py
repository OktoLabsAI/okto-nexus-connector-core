"""Private saved-history evidence for one reviewed Claude stream-json conversation."""

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..protocol import strict_json
from .claude_history_identity import claude_session_uuid
from .saved_history_file import file_identity, file_version, plain_path

_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_LINE_BYTES = 4 * 1024 * 1024
_MAX_CLOSE_BYTES = 64 * 1024
_COST_STATE_KEYS = {
    "type", "sessionId", "totalCostUSD", "totalAPIDuration", "totalAPIDurationWithoutRetries",
    "totalToolDuration", "totalLinesAdded", "totalLinesRemoved", "totalDuration", "startTime",
    "modelUsage", "hasUnknownModelCost",
}


@dataclass(frozen=True, slots=True)
class ClaudeSavedHistory:
    session_uuid: str = field(repr=False)
    state_home: str = field(repr=False)
    workspace: str = field(repr=False)
    home_identity: tuple[int, int]
    workspace_identity: tuple[int, int]
    file_identity: tuple[int, int]
    byte_size: int
    sha256: str


def observe_claude_saved_history(state_home: str, session_uuid: str, cwd: str, *,
                                before_close: ClaudeSavedHistory | None = None) -> ClaudeSavedHistory | None:
    """Hash one regular JSONL file and optionally prove its exact live prefix.

    The reviewed Claude CLI appends cost metadata while the stream owner exits.
    Any new dialogue, different inode, or changed prefix invalidates retirement.
    The caller must independently establish canonical close and process release.
    """
    file = claude_history_path(state_home, session_uuid, cwd)
    if file is None:
        return None
    home, workspace = Path(state_home), Path(cwd)
    try:
        for parent in file.parents:
            plain_path(parent, directory=True)
        workspace_identity = file_identity(plain_path(workspace, directory=True))
        home_identity = file_identity(plain_path(home, directory=True))
        original = file_version(plain_path(file, directory=False))
        size = original[2]
        if not 0 < size <= _MAX_FILE_BYTES:
            return None
        prefix_size = size
        if before_close is not None:
            if (before_close.session_uuid != session_uuid or before_close.state_home != str(home)
                    or before_close.workspace != str(workspace) or before_close.home_identity != home_identity
                    or before_close.workspace_identity != workspace_identity
                    or before_close.file_identity != original[:2]
                    or not 0 < before_close.byte_size <= size <= before_close.byte_size + _MAX_CLOSE_BYTES):
                return None
            prefix_size = before_close.byte_size
        digest = hashlib.sha256()
        dialogue = set()
        pending_snapshot = None
        with file.open("rb") as stream:
            opened = file_version(os.fstat(stream.fileno()))
            if opened[:4] != original[:4]:
                return None
            while stream.tell() < size:
                position = stream.tell()
                closing_metadata = position >= prefix_size
                if closing_metadata and position == prefix_size and digest.hexdigest() != before_close.sha256:
                    return None
                boundary = size if closing_metadata else prefix_size
                line = stream.readline(min(_MAX_LINE_BYTES + 1, boundary - position))
                if not line.endswith(b"\n") or len(line) > _MAX_LINE_BYTES:
                    return None
                record = strict_json(line.decode("utf-8"))
                if type(record) is not dict:
                    return None
                if closing_metadata:
                    if (record.get("sessionId") != session_uuid or record.get("type") != "cost-state"
                            or record.keys() != _COST_STATE_KEYS):
                        return None
                else:
                    kind = record.get("type")
                    if "sessionId" not in record and kind == "file-history-snapshot":
                        if pending_snapshot is not None:
                            return None
                        pending_snapshot = _empty_snapshot_message(record)
                        if pending_snapshot is None:
                            return None
                        digest.update(line)
                        continue
                    if record.get("sessionId") != session_uuid:
                        return None
                    native_cwd = record.get("cwd")
                    if (kind in ("user", "assistant") or "cwd" in record) and (
                            type(native_cwd) is not str or Path(native_cwd) != workspace):
                        return None
                    if kind in ("user", "assistant") and record.get("isSidechain") is False:
                        if pending_snapshot is not None:
                            if kind != "user" or record.get("uuid") != pending_snapshot:
                                return None
                            pending_snapshot = None
                        dialogue.add(kind)
                digest.update(line)
            if file_version(os.fstat(stream.fileno())) != opened:
                return None
        if pending_snapshot is not None or dialogue != {"user", "assistant"} or (
                before_close is not None and size == prefix_size and digest.hexdigest() != before_close.sha256):
            return None
        for parent in file.parents:
            plain_path(parent, directory=True)
        if (file_identity(plain_path(home, directory=True)) != home_identity
                or file_identity(plain_path(workspace, directory=True)) != workspace_identity
                or file_version(plain_path(file, directory=False)) != original):
            return None
        return ClaudeSavedHistory(session_uuid, str(home), str(workspace), home_identity, workspace_identity, original[:2],
                                  size, digest.hexdigest())
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def _empty_snapshot_message(record):
    """Recognize the reviewed interactive build's empty, pre-message file snapshot."""
    snapshot = record.get("snapshot")
    message_id = claude_session_uuid(record.get("messageId"))
    if (record.keys() != {"type", "messageId", "snapshot", "isSnapshotUpdate"}
            or message_id is None or record["isSnapshotUpdate"] is not False or type(snapshot) is not dict
            or snapshot.keys() != {"messageId", "trackedFileBackups", "timestamp"}
            or snapshot["messageId"] != message_id or snapshot["trackedFileBackups"] != {}
            or type(snapshot["timestamp"]) is not str
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z",
                                snapshot["timestamp"])):
        return None
    return message_id


def claude_history_path(state_home, session_uuid, cwd):
    """Resolve only the reviewed native path for this exact local conversation."""
    if claude_session_uuid(session_uuid) is None or any(type(value) is not str or not value
                                                      for value in (state_home, cwd)):
        return None
    home, workspace = Path(state_home), Path(cwd)
    if (not home.is_absolute() or not workspace.is_absolute()
            or ".." in home.parts or ".." in workspace.parts):
        return None
    # Avoid enumerating other projects or accepting an arbitrary transcript path.
    if not cwd.isascii() or len(cwd) > 180:
        return None
    directory = re.sub(r"[^A-Za-z0-9]", "-", str(workspace))
    return home / "projects" / directory / f"{session_uuid}.jsonl"
