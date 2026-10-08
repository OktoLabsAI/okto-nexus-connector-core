"""Durable completion proof from the owned Linux subreaper.

The native child never inherits the receipt descriptor. Only the guardian
marks it after reaping every child; loss of a PID alone proves nothing.
Receipts live in a private per-user, per-host directory across owner restarts.
"""
import os
import re
import secrets
import stat
import time

_STOPPED = b'nexus-linux-tree-stopped-v1\n'


def _directory():
    path = f'/tmp/nexus-core-containers-{os.getuid()}'
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(descriptor)
        raise PermissionError('Unsafe owned-container receipt directory')
    return descriptor


def create_receipt():
    identity = 'linux-guardian:' + secrets.token_hex(16)
    directory = _directory()
    descriptor = None
    try:
        descriptor = os.open(identity.split(':')[1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=directory)
        os.fsync(directory)
        return identity, descriptor
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
            os.unlink(identity.split(':')[1], dir_fd=directory)
        raise
    finally:
        os.close(directory)


def mark_stopped(descriptor):
    # Called only after no child was launched or waitpid proved there are no
    # remaining children. A failed commit remains unknown to the next owner.
    if os.write(descriptor, _STOPPED) != len(_STOPPED):
        raise OSError('Incomplete owned-container completion receipt')
    os.fsync(descriptor)


def recover_receipt(identity, *, timeout_seconds=0):
    if type(identity) is not str or re.fullmatch(r'linux-guardian:[0-9a-f]{32}', identity) is None:
        return 'UNKNOWN'
    deadline = time.monotonic() + timeout_seconds
    while True:
        directory = descriptor = None
        try:
            directory = _directory()
            descriptor = os.open(identity.split(':')[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 dir_fd=directory)
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                return 'UNKNOWN'
            if info.st_size == len(_STOPPED) and os.read(descriptor, len(_STOPPED) + 1) == _STOPPED:
                return 'STOPPED'
        except OSError:
            return 'UNKNOWN'
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory is not None:
                os.close(directory)
        if time.monotonic() >= deadline:
            return 'UNKNOWN'
        time.sleep(min(.02, max(0, deadline - time.monotonic())))
