"""Read-only proof of an exact Codex app-server rollout in its state home."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from ..harness_configuration import harness_settings_dict
from ..identifiers import is_codex_thread_id
from ..models import CodexRolloutEvidence, CoreError, PreparedLaunch
from ..protocol import canonical_json, strict_json
from .saved_history_file import file_identity as _identity, file_version as _file_version, plain_path as _plain

_MAX_HEADER_BYTES = 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
CODEX_SAVED_HISTORY_BUILD = (
    "0.157.0", "win32", "x86_64",
    "sha256:ed1c7b36e44536809c868864c833af8a857f56599a7a7fe23b908a1ba1093b1f",
)


def saved_launch_configuration(prepared: PreparedLaunch) -> dict[str, str]:
    """Compare launch configuration while allowing a fresh session-scoped tool grant."""
    intent = prepared.intent
    session_refs = ('mcp-cap:', 'native-cap:') if intent.adapter_id == 'pi_rpc' else ('mcp-cap:',)
    inputs = dict(adapter_id=intent.adapter_id, mode=intent.mode, model=intent.model, argv=list(prepared.argv),
        harness_settings=harness_settings_dict(intent.harness_settings), mcp_preset=list(intent.mcp_preset),
        credential_refs=sorted(ref for ref in prepared.secret_refs if not ref.startswith(session_refs)))
    return dict(profile_fingerprint=prepared.profile_fingerprint, root_fingerprint=prepared.root_fingerprint,
                resume_configuration_sha256=hashlib.sha256(canonical_json(inputs)).hexdigest())


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


def publish_rollout(source: Path, destination: Path, state_home: Path, digest: str) -> None:
    """Atomically stage only the exact, self-contained rollout in an owned profile."""
    _plain(state_home, directory=True)
    parts = destination.relative_to(state_home / 'sessions').parts
    if not parts or '..' in parts or not destination.name.startswith('rollout-') or destination.suffix != '.jsonl':
        raise CoreError('PROFILE_DRIFT', 'saved_codex_resume', retry_safe=True)
    parent = state_home
    for part in ('sessions', *parts[:-1]):
        parent /= part
        parent.mkdir(exist_ok=True)
        _plain(parent, directory=True)
    _plain(source, directory=False)
    with source.open('rb') as input_file:
        first = input_file.readline(_MAX_HEADER_BYTES + 1)
        record = strict_json(first.decode()) if len(first) <= _MAX_HEADER_BYTES and first.endswith(b'\n') else None
        metadata = record.get('payload') if type(record) is dict and record.get('type') == 'session_meta' else None
        if not isinstance(metadata, dict):
            raise CoreError('PROFILE_DRIFT', 'saved_codex_resume', retry_safe=True)
        if any(metadata.get(key) is not None for key in ('history_base', 'forked_from_id', 'parent_thread_id')):
            raise CoreError('CAPABILITY_UNSUPPORTED', 'saved_codex_resume', retry_safe=True)
        try:
            _plain(destination, directory=False)
        except FileNotFoundError:
            pass
        else:
            return  # The caller verifies the bytes and identity of an existing copy.
        with tempfile.NamedTemporaryFile(mode='w+b', dir=parent, prefix='.nexus-rollout-', delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(first)
                shutil.copyfileobj(input_file, output, length=_CHUNK_BYTES)
                output.flush()
                os.fsync(output.fileno())
                output.seek(0)
                if hashlib.file_digest(output, 'sha256').hexdigest() != digest:
                    raise CoreError('PROFILE_DRIFT', 'saved_codex_resume', retry_safe=True)
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            if os.name == 'nt':
                temporary.rename(destination)
            else:
                os.link(temporary, destination)
        except FileExistsError:
            _plain(destination, directory=False)
        finally:
            temporary.unlink(missing_ok=True)
