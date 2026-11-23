"""Private proof of the reviewed hosted Pi session file and native leaf."""

from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import Path
import re

from ..protocol import strict_json
from .saved_history_file import file_identity, file_version, plain_path

_MAX_BYTES = 64 * 1024 * 1024
_MAX_LINE = 4 * 1024 * 1024
_MAX_ENTRIES = 100_000
_SESSION_ID = re.compile(r"hsess_[0-9a-f]{32}")
_ENTRY_ID = re.compile(r"[0-9a-f]{8}")


@dataclass(frozen=True, slots=True)
class PiSavedHistory:
    session_id: str = field(repr=False)
    agent_dir: str = field(repr=False)
    workspace: str = field(repr=False)
    session_file: str = field(repr=False)
    leaf_id: str = field(repr=False)
    entry_count: int
    agent_dir_identity: tuple[int, int]
    workspace_identity: tuple[int, int]
    file_identity: tuple[int, int]
    byte_size: int
    sha256: str


def observe_pi_saved_history(agent_dir: str, workspace: str, session_file: str, session_id: str,
                             leaf_id: str, entry_count: int) -> PiSavedHistory | None:
    """Read the exact flushed file and prove that reopening would select the same branch."""
    if (not all(type(arg) is str and arg for arg in (agent_dir, workspace, session_file, session_id, leaf_id))
            or _SESSION_ID.fullmatch(session_id) is None or _ENTRY_ID.fullmatch(leaf_id) is None
            or type(entry_count) is not int or not 2 <= entry_count <= _MAX_ENTRIES):
        return None
    home, cwd, file = map(Path, (agent_dir, workspace, session_file))
    if any(not path.is_absolute() or ".." in path.parts for path in (home, cwd, file)):
        return None
    encoded_cwd = re.sub(r"[/\\:]", "-", str(cwd).lstrip("/\\"))
    if file.parent != home / "sessions" / f"--{encoded_cwd}--" or not file.name.endswith(f"_{session_id}.jsonl"):
        return None
    try:
        for parent in set(file.parents) | set(cwd.parents):
            plain_path(parent, directory=True)
        home_identity = file_identity(plain_path(home, directory=True))
        cwd_identity = file_identity(plain_path(cwd, directory=True))
        version = file_version(plain_path(file, directory=False))
        if not 0 < version[2] <= _MAX_BYTES:
            return None
        digest = sha256()
        entries = {}
        consumed = 0
        with file.open("rb") as handle:
            opened = file_version(os.fstat(handle.fileno()))
            # Windows can report creation time at different precision for the
            # open handle. Other file fields agree and each view stays stable.
            if opened[:4] != version[:4]:
                return None
            while raw := handle.readline(_MAX_LINE + 1):
                consumed += len(raw)
                if consumed > version[2] or len(raw) > _MAX_LINE or not raw.endswith(b"\n"):
                    return None
                document = strict_json(raw.decode("utf-8"))
                if type(document) is not dict:
                    return None
                if consumed == len(raw):
                    if (document.get("type") != "session" or document.get("version") != 3
                            or document.get("id") != session_id or "parentSession" in document
                            or type(document.get("cwd")) is not str or Path(document["cwd"]) != cwd):
                        return None
                else:
                    entry = document.get("id")
                    parent = document.get("parentId")
                    if (len(entries) == entry_count or document.get("type") == "session"
                            or type(entry) is not str or _ENTRY_ID.fullmatch(entry) is None or entry in entries
                            or (parent is not None and (type(parent) is not str or parent not in entries))):
                        return None
                    message = document.get("message")
                    role = message.get("role") if document.get("type") == "message" and type(message) is dict else None
                    stop = message.get("stopReason") if role == "assistant" else None
                    entries[entry] = (parent, role, stop)
                digest.update(raw)
            if (len(entries) != entry_count or next(reversed(entries)) != leaf_id or consumed != version[2]
                    or file_version(os.fstat(handle.fileno())) != opened):
                return None
        if (file_version(plain_path(file, directory=False)) != version
                or file_identity(plain_path(home, directory=True)) != home_identity
                or file_identity(plain_path(cwd, directory=True)) != cwd_identity):
            return None
        # Exclude empty, user-only and last-turn-interrupted branches.
        cursor = leaf_id
        assistant = user = False
        while cursor is not None:
            cursor, role, stop = entries[cursor]
            if role == "assistant" and not assistant:
                if stop not in ("stop", "length"):
                    return None
                assistant = True
            if role == "user":
                if not assistant:
                    return None
                user = True
                break
        if not user:
            return None
        return PiSavedHistory(session_id, str(home), str(cwd), str(file), leaf_id, entry_count,
                              home_identity, cwd_identity, version[:2], consumed, digest.hexdigest())
    except (OSError, TypeError, ValueError, RecursionError):
        return None


def pi_saved_history_current(history: PiSavedHistory) -> bool:
    if type(history) is not PiSavedHistory:
        return False
    return observe_pi_saved_history(history.agent_dir, history.workspace, history.session_file,
                                    history.session_id, history.leaf_id, history.entry_count) == history
