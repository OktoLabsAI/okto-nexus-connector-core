"""Read-only proof of an exact Codex app-server rollout in its state home."""

import hashlib
import os
from pathlib import Path

from ..identifiers import is_codex_thread_id
from ..models import CodexRolloutEvidence
from ..protocol import strict_json
from .saved_history_file import file_identity as _identity, file_version as _file_version, plain_path as _plain

_MAX_HEADER_BYTES = 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
CODEX_SAVED_HISTORY_BUILD = (
    "0.157.0", "win32", "x86_64",
    "sha256:ed1c7b36e44536809c868864c833af8a857f56599a7a7fe23b908a1ba1093b1f",
)


def observe_rollout(state_home: str | None, path: str | None,
                    thread_id: str, cwd: str) -> CodexRolloutEvidence | None:
    """Accept the native-selected plain file only, with stable bytes and exact header.

    The initial record is bounded. The body is hashed as a byte stream,
    without decoding or returning transcript content.
    """
    if (not is_codex_thread_id(thread_id)
            or any(type(value) is not str or not value for value in (state_home, path, cwd))):
        return None
    try:
        home, file, workspace = Path(state_home), Path(path), Path(cwd)
        if (not home.is_absolute() or not file.is_absolute() or not workspace.is_absolute()
                or ".." in home.parts or ".." in file.parts or not file.is_relative_to(home / "sessions")
                or not file.name.startswith("rollout-") or file.suffix != ".jsonl"):
            return None
        for parent in file.parents:
            _plain(parent, directory=True)
        home_before = _identity(_plain(home, directory=True))
        original = _file_version(_plain(file, directory=False))
        with file.open("rb") as stream:
            opened = _file_version(os.fstat(stream.fileno()))
            # Windows can report different ctime fields for a pathname and
            # an open handle. Compare that field only within each source.
            if opened[:4] != original[:4]:
                return None
            first = stream.readline(_MAX_HEADER_BYTES + 1)
            if not 0 < len(first) <= _MAX_HEADER_BYTES or not first.endswith(b"\n"):
                return None
            record = strict_json(first.decode("utf-8"))
            header = record.get("payload") if type(record) is dict and record.get("type") == "session_meta" else None
            if (type(header) is not dict or header.get("id") != thread_id
                    or type(header.get("cwd")) is not str
                    or Path(header["cwd"]) != workspace):
                return None
            file_size = original[2]
            if file_size <= len(first):
                return None
            digest = hashlib.sha256(first)
            while stream.tell() < file_size:
                chunk = stream.read(min(_CHUNK_BYTES, file_size - stream.tell()))
                if not chunk:
                    return None
                digest.update(chunk)
            if not chunk.endswith(b"\n") or _file_version(os.fstat(stream.fileno())) != opened:
                return None
        for parent in file.parents:
            _plain(parent, directory=True)
        if (_identity(_plain(home, directory=True)) != home_before
                or _file_version(_plain(file, directory=False)) != original):
            return None
        return CodexRolloutEvidence(thread_id, str(home), file.relative_to(home).parts,
                                   home_before, original[:2], file_size, digest.hexdigest())
    except (OSError, ValueError, RecursionError):
        # Provider paths/content remain private even on malformed input or I/O failure.
        return None
