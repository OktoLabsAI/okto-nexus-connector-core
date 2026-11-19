"""Describe and revalidate the exact workspace file reviewed for Claude Read."""

import re
from pathlib import Path

from ..models import EffectNotSent
from .saved_history_file import file_identity, file_version, plain_path


class ClaudeReadTargetChanged(EffectNotSent):
    def __init__(self):
        super().__init__("The file changed after the Claude Read request.", code="STALE_TURN")


def valid_claude_read_arguments(value):
    if type(value) is not dict or set(value) - {"file_path", "offset", "limit", "pages"}:
        return False
    name = value.get("file_path")
    if type(name) is not str or not 0 < len(name) <= 2048 or not name.isprintable():
        return False
    if any(type(value[key]) is not int or not 0 <= value[key] <= 2**31 - 1
           for key in ("offset", "limit") if key in value):
        return False
    pages = value.get("pages")
    return "pages" not in value or (type(pages) is str and 0 < len(pages) <= 64
                                    and re.fullmatch(r"[0-9,-]+", pages) is not None)


def review_claude_read(cwd, value):
    """Return reviewed relative arguments and a pre-write identity assertion."""
    if not valid_claude_read_arguments(value):
        raise ValueError("Unsupported Claude Read arguments.")
    root, target = Path(cwd), Path(value["file_path"])
    if not root.is_absolute() or not target.is_absolute() or ".." in target.parts:
        raise ValueError("Claude Read must name a file in the reviewed workspace.")
    relative = target.relative_to(root)
    if not relative.parts or any(":" in part for part in relative.parts):
        raise ValueError("Claude Read must name a regular workspace file.")

    def observe():
        parents = tuple(file_identity(plain_path(path, directory=True)) for path in target.parents)
        return parents, file_version(plain_path(target, directory=False))

    witness = observe()

    def require_current():
        try:
            if observe() == witness:
                return
        except (OSError, ValueError):
            pass
        raise ClaudeReadTargetChanged()

    return {**value, "file_path": relative.as_posix()}, require_current
