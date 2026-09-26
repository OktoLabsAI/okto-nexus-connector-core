"""Local, cooperative atomic persistence for an explicitly selected config.

The trusted host owns path selection and user approval. The adjacent lock is
cross-process but advisory: non-cooperating writers can still race the final
check/replace. Never pass a network-supplied path to this module directly.
"""

from __future__ import annotations

import os
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .config_document import (JsonConfigPlan, TomlConfigPlan, apply_json_plan,
                              apply_toml_plan)
from .models import CoreError

_MAX_CONFIG_BYTES = 1024 * 1024
_LOCK_POLL_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class ConfigApplyResult:
    changed: bool
    backup_path: Path | None
    bytes_written: int


def _open_regular(path: Path) -> int | None:
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode):
        raise CoreError("PROFILE_DRIFT", "config_apply")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CoreError("PROFILE_DRIFT", "config_apply") from exc
    after = os.fstat(fd)
    if (not stat.S_ISREG(after.st_mode) or
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)):
        os.close(fd)
        raise CoreError("PROFILE_DRIFT", "config_apply")
    return fd


def _read_document(path: Path) -> tuple[bytes | None, int | None]:
    fd = _open_regular(path)
    if fd is None:
        return None, None
    try:
        mode = stat.S_IMODE(os.fstat(fd).st_mode)
        with os.fdopen(fd, "rb") as source:
            data = source.read(_MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        raise CoreError("PROFILE_DRIFT", "config_apply") from exc
    if len(data) > _MAX_CONFIG_BYTES:
        raise CoreError("CAPACITY_EXCEEDED", "config_apply")
    return data, mode


def _write_new(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _sync_directory(parent: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _file_lock(path: Path, timeout_seconds: float):
    if timeout_seconds < 0:
        raise ValueError("lock timeout must be nonnegative")
    if path.is_symlink():
        raise CoreError("PROFILE_DRIFT", "config_lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CoreError("PROFILE_DRIFT", "config_lock") from exc
    try:
        opened = os.fstat(fd)
        named = path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or
                not stat.S_ISREG(named.st_mode) or
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise CoreError("PROFILE_DRIFT", "config_lock")
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise CoreError("CONFIG_LOCK_BUSY", "config_lock",
                                    retry_safe=True) from exc
                time.sleep(min(_LOCK_POLL_SECONDS, deadline - time.monotonic()))
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def apply_json_plan_file(plan: JsonConfigPlan, selected_path: Path, *,
                         lock_timeout_seconds: float = 5.0) -> ConfigApplyResult:
    """Apply a host-approved plan to a local file with backup and CAS.

    Only callers that cooperate on the adjacent lock get serializable writes.
    Failure before replace leaves the source intact. A crash after replace may
    leave a backup, but never a partial target file. On Windows, the new file
    and backup inherit the selected directory's ACL; the trusted host must
    verify that ACL before applying a plan containing sensitive values.
    """
    return _apply_plan_file(plan, selected_path, apply_json_plan,
                            lock_timeout_seconds=lock_timeout_seconds)


def apply_toml_plan_file(plan: TomlConfigPlan, selected_path: Path, *,
                         lock_timeout_seconds: float = 5.0) -> ConfigApplyResult:
    """Apply a host-approved Codex TOML plan under the same CAS/backup lock."""
    return _apply_plan_file(plan, selected_path, apply_toml_plan,
                            lock_timeout_seconds=lock_timeout_seconds)


def _apply_plan_file(plan, selected_path: Path, apply_plan, *,
                     lock_timeout_seconds: float) -> ConfigApplyResult:
    path = Path(selected_path)
    if not path.is_absolute() or not path.parent.is_dir():
        raise CoreError("WORKSPACE_UNAVAILABLE", "config_apply")
    lock_path = path.with_name(path.name + ".lock")
    with _file_lock(lock_path, lock_timeout_seconds):
        current, mode = _read_document(path)
        replacement = apply_plan(plan, current)
        if not plan.changed:
            return ConfigApplyResult(False, None, 0)
        backup: Path | None = None
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            if current is not None:
                backup = path.with_name(f"{path.name}.{uuid4().hex}.bak")
                _write_new(backup, current)
                _sync_directory(path.parent)
            _write_new(temp, replacement, mode=mode or 0o600)
            # A cooperating writer cannot intervene under the lock; repeat
            # the read for a best-effort guard against external edits.
            latest, _ = _read_document(path)
            apply_plan(plan, latest)
            os.replace(temp, path)
            try:
                _sync_directory(path.parent)
            except OSError as exc:
                raise CoreError("OUTCOME_UNKNOWN", "config_apply",
                                possible_effect=True) from exc
            return ConfigApplyResult(True, backup, len(replacement))
        finally:
            if temp.exists():
                temp.unlink()
