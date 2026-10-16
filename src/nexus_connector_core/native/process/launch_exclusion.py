"""Host-local exclusion per durable producer, independent of every sibling.

The lock is only a critical-section primitive, never evidence of termination.
Every holder must re-read the durable launch record, including after an
abandoned Windows mutex. A producer cannot infer permission from lock ownership.
"""
from contextlib import contextmanager
import os
import re
import stat
from typing import ContextManager, Protocol


class LaunchGateBusy(RuntimeError):
    """Another producer/recovery worker still owns this exact frontier."""


class LaunchExclusion(Protocol):
    def hold(self, producer_id: str) -> ContextManager[None]: ...


class HostLaunchExclusion:
    """Nonblocking OS exclusion; callers retain/retry their own work item."""
    @contextmanager
    def hold(self, producer_id):
        if type(producer_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', producer_id):
            raise ValueError('Invalid launch producer identity')
        with (_windows(producer_id) if os.name == 'nt' else _posix(producer_id)):
            yield


@contextmanager
def _windows(producer_id):
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes, create.restype = [ctypes.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE
    wait = kernel.WaitForSingleObject
    wait.argtypes, wait.restype = [w.HANDLE, w.DWORD], w.DWORD
    release = kernel.ReleaseMutex
    release.argtypes, release.restype = [w.HANDLE], w.BOOL
    close = kernel.CloseHandle
    close.argtypes, close.restype = [w.HANDLE], w.BOOL
    handle = create(None, False, 'Global\\nexus-core-launch-'+producer_id)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        result = wait(handle, 0)
        if result == 0x102:  # WAIT_TIMEOUT, never an implicit wait on siblings.
            raise LaunchGateBusy('Launch producer is still in its critical section')
        if result not in (0, 0x80):  # WAIT_OBJECT_0 or WAIT_ABANDONED
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = True
        yield
    finally:
        try:
            if acquired and not release(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close(handle)


@contextmanager
def _posix(producer_id):
    import fcntl
    # As with Linux containment receipts: private local-host state, outside
    # the canonical database and never interpreted as a durable outcome.
    directory = f'/tmp/nexus-core-launch-fences-{os.getuid()}'
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    fd = None
    try:
        info = os.fstat(dir_fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise PermissionError('Unsafe launch exclusion directory')
        fd = os.open(producer_id, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=dir_fd)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise PermissionError('Unsafe launch exclusion file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LaunchGateBusy('Launch producer is still in its critical section') from None
        yield
    finally:
        if fd is not None:
            os.close(fd)  # releases flock, including exception paths
        os.close(dir_fd)
        # Never unlink: an old open descriptor and a replacement inode could
        # otherwise create two independent locks for one producer identity.
