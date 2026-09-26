"""Historical birth identity for Core-owned process containers.

This is diagnostic evidence, not a transferable process handle or authority
to signal a PID after restart. The OS containment remains the ownership fence.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys

from ...models import ProcessBirthEvidence


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


def _windows_birth_token(handle: int) -> str:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_times = kernel.GetProcessTimes
    get_times.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(_FileTime)] * 4)]
    get_times.restype = wintypes.BOOL
    created, exited, kernel_time, user_time = (_FileTime() for _ in range(4))
    if not get_times(handle, ctypes.byref(created), ctypes.byref(exited),
                     ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    return f"filetime:{created.high:08x}{created.low:08x}"


def _linux_birth_token(pid: int) -> tuple[str, str]:
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
        encoding="ascii").strip()
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    end_comm = stat.rfind(")")
    if end_comm < 0 or not boot_id:
        raise ValueError("invalid Linux process birth evidence")
    # The comm field may itself contain spaces and closing parentheses.
    fields = stat[end_comm + 2:].split()
    if len(fields) <= 19 or int(stat.split(" ", 1)[0]) != pid:
        raise ValueError("invalid Linux process birth evidence")
    return f"boot-start:{boot_id}:{int(fields[19])}", fields[0]


def snapshot_owned_process_birth(process: subprocess.Popen) -> ProcessBirthEvidence:
    """Read an OS birth token from the exact Core-owned process handle."""
    if sys.platform == "win32":
        from .windows_process import OwnedWindowsPopen

        if not isinstance(process, OwnedWindowsPopen):
            raise TypeError("not a Core-owned Windows process")

        return ProcessBirthEvidence(
            "win32", process.pid, _windows_birth_token(process._handle),
            "windows_job")

    if sys.platform == "linux":
        from .linux_process import OwnedLinuxPopen

        if not isinstance(process, OwnedLinuxPopen):
            raise TypeError("not a Core-owned Linux process")
        token, state = _linux_birth_token(process.pid)
        if state in {"Z", "X", "x"}:
            raise RuntimeError("owned process is already stopped")
        return ProcessBirthEvidence(
            "linux", process.pid, token,
            "linux_guardian")

    raise RuntimeError("owned process birth identity unqualified on this platform")


def observe_recorded_process_birth(evidence: ProcessBirthEvidence) -> str:
    """Read one PID's current birth; never infer ownership or authorize kill."""
    if (not isinstance(evidence, ProcessBirthEvidence) or
            evidence.platform != sys.platform or
            type(evidence.pid) is not int or evidence.pid <= 0):
        return "UNKNOWN"

    if sys.platform == "linux":
        try:
            token, state = _linux_birth_token(evidence.pid)
        except FileNotFoundError:
            return "NOT_OBSERVED"
        except (OSError, ValueError):
            return "UNKNOWN"
        if token != evidence.birth_token:
            return "DIFFERENT_BIRTH"
        return "NOT_RUNNING" if state in {"Z", "X", "x"} else "MATCHING_LIVE"

    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        close_handle = kernel.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        wait = kernel.WaitForSingleObject
        wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait.restype = wintypes.DWORD
        # QUERY_LIMITED_INFORMATION reads birth; SYNCHRONIZE permits a
        # zero-time wait to distinguish a still-running from an exited object.
        handle = open_process(0x101000, False, evidence.pid)
        if not handle:
            return "NOT_OBSERVED" if ctypes.get_last_error() == 87 else "UNKNOWN"
        try:
            try:
                token = _windows_birth_token(handle)
            except OSError:
                return "UNKNOWN"
            if token != evidence.birth_token:
                return "DIFFERENT_BIRTH"
            wait_result = wait(handle, 0)
            if wait_result == 0x102:  # WAIT_TIMEOUT: running at observation.
                return "MATCHING_LIVE"
            if wait_result == 0:  # WAIT_OBJECT_0: exited object still exists.
                return "NOT_RUNNING"
            return "UNKNOWN"
        finally:
            close_handle(handle)

    return "UNKNOWN"
