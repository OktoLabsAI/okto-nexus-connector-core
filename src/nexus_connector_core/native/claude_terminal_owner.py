"""Verify a saved Claude conversation against the exact owned Windows terminal."""

import os
import re
from pathlib import Path

from ..models import ProcessBirthEvidence
from ..protocol import strict_json
from .claude_history_identity import claude_session_uuid
from .claude_saved_history import ClaudeSavedHistory
from .saved_history_file import file_identity, file_version, plain_path

_REVIEWED_VERSION = "2.1.328"
_MAX_REGISTRY_BYTES = 64 * 1024


def observe_claude_terminal_owner(
    terminal, history: ClaudeSavedHistory, birth: ProcessBirthEvidence,
) -> bool:
    """Corroborate the adopted UUID using the held handle and Claude's local registry.

    Call after launching the reviewed build and before enabling any input.
    This observation does not decide whether the source is retired, whether
    the effective settings are approved, or whether a launch is authorized.
    """
    if (birth.platform != "win32" or birth.containment != "windows_job"
            or type(birth.pid) is not int or birth.pid <= 0
            or not re.fullmatch(r"filetime:[a-f0-9]{16}", birth.birth_token)
            or claude_session_uuid(history.session_uuid) is None):
        return False
    home, workspace = Path(history.state_home), Path(history.workspace)
    if (not home.is_absolute() or not workspace.is_absolute()
            or ".." in home.parts or ".." in workspace.parts):
        return False
    registry = home / "sessions" / f"{birth.pid}.json"
    try:
        if terminal.poll() is not None or terminal.birth != birth:
            return False
        original = _registry_version(registry, home, workspace, history)
        if not 0 < original[2] <= _MAX_REGISTRY_BYTES:
            return False
        with registry.open("rb") as stream:
            opened = file_version(os.fstat(stream.fileno()))
            if opened[:4] != original[:4]:
                return False
            body = stream.read(_MAX_REGISTRY_BYTES + 1)
            if len(body) != original[2] or file_version(os.fstat(stream.fileno())) != opened:
                return False
        record = strict_json(body.decode("utf-8"))
        if type(record) is not dict:
            return False
        cwd = record.get("cwd")
        return (
            type(record.get("pid")) is int and record["pid"] == birth.pid
            and record.get("procStart") == str(int(birth.birth_token.removeprefix("filetime:"), 16))
            and record.get("sessionId") == history.session_uuid
            and type(cwd) is str and Path(cwd) == workspace
            and record.get("version") == _REVIEWED_VERSION
            and record.get("kind") == "interactive" and record.get("entrypoint") == "cli"
            and record.get("status") == "idle"
            and _registry_version(registry, home, workspace, history) == original
            and terminal.birth == birth and terminal.poll() is None
        )
    except (OSError, ValueError, TypeError, RecursionError):
        return False


def _registry_version(registry, home, workspace, history):
    for parent in registry.parents:
        plain_path(parent, directory=True)
    if (file_identity(plain_path(home, directory=True)) != history.home_identity
            or file_identity(plain_path(workspace, directory=True)) != history.workspace_identity):
        raise ValueError("The saved Claude state or workspace directory changed.")
    return file_version(plain_path(registry, directory=False))
