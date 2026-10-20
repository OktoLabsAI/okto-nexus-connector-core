"""Durable stop proof for a planned Darwin launchd guardian.

The guardian writes the receipt only after a complete coalition drain. A new
owner can read that exact proof without trusting a historical PID or the
observer's lost AF_UNIX final frame.
"""

import os
import re
import stat
import time


_STOPPED = b'nexus-darwin-tree-stopped-v1\n'
_IDENTITY = re.compile(
    r'darwin-launchd:(ai\.oktolabs\.nexus-owned\.[0-9]+\.[0-9a-f]{16})\Z')


def _name(identity):
    match = _IDENTITY.fullmatch(identity) if type(identity) is str else None
    if match is None:
        raise ValueError('Invalid planned Darwin container')
    return match.group(1)


def _directory():
    path = f'/tmp/nexus-core-darwin-containers-{os.getuid()}'
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    descriptor = os.open(
        path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(descriptor)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        os.close(descriptor)
        raise PermissionError('Unsafe Darwin owned-container receipt directory')
    return descriptor


def _open_receipt(identity, flags):
    directory = _directory()
    try:
        descriptor = os.open(
            _name(identity), flags | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=directory)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            os.close(descriptor)
            raise PermissionError('Unsafe Darwin owned-container receipt')
        return descriptor
    finally:
        os.close(directory)


def create_receipt(identity):
    """Create an empty receipt before asking launchd to start the guardian."""
    descriptor = _open_receipt(identity, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        directory = _directory()
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(descriptor)


def mark_stopped(identity):
    """Guardian-only call after the coalition and native leader are reaped."""
    descriptor = _open_receipt(identity, os.O_WRONLY)
    try:
        if os.fstat(descriptor).st_size != 0:
            raise OSError('Darwin stop receipt is not empty')
        if os.write(descriptor, _STOPPED) != len(_STOPPED):
            raise OSError('Incomplete Darwin stop receipt')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def recover_receipt(identity, *, timeout_seconds=0):
    """Return STOPPED only for the exact durable guardian proof."""
    try:
        _name(identity)
    except ValueError:
        return 'UNKNOWN'
    deadline = time.monotonic() + timeout_seconds
    while True:
        descriptor = None
        try:
            descriptor = _open_receipt(identity, os.O_RDONLY)
            info = os.fstat(descriptor)
            if (info.st_size == len(_STOPPED)
                    and os.read(descriptor, len(_STOPPED) + 1) == _STOPPED):
                return 'STOPPED'
        except OSError:
            return 'UNKNOWN'
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if time.monotonic() >= deadline:
            return 'UNKNOWN'
        time.sleep(min(.02, max(0, deadline - time.monotonic())))
