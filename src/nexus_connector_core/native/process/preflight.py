"""Passive containment preflight for managed launches (C1/PC11).

The audit environment lacked a guardian requirement, and managed work
still spawned. Preflight verifies the *actual* backend requirements
before any provider spawn or active probe, without executing wrappers,
reading secrets or creating provider trees. Limitations return the typed
``PROCESS_CONTAINMENT_UNAVAILABLE`` with the missing requirement - never
a silent fallback to bare ``kill(pid)``.
"""

from __future__ import annotations

import ctypes
import os
import sys

from ...models import CoreError

__all__ = ["containment_preflight", "containment_requirements"]

_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "win32": ("job_objects",),
    "linux": ("procfs", "proc_children", "pidfd", "subreaper"),
}


def containment_requirements(platform: str = None) -> tuple[str, ...]:
    return _REQUIREMENTS.get(platform or sys.platform, ())


def _check_windows() -> dict[str, str]:
    status = {}
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        # C2 (§6 review): explicit 64-bit Win32 ABI declarations with
        # validated returns, per the same ABI discipline R07 imposed on
        # the Linux side. Qualified separately from Linux - a Linux pass
        # never implies Win32 validity.
        from ctypes import wintypes
        kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            status["job_objects"] = (
                f"CreateJobObjectW failed (WinError {ctypes.get_last_error()})")
        elif not kernel.CloseHandle(job):
            status["job_objects"] = (
                f"CloseHandle failed (WinError {ctypes.get_last_error()})")
        else:
            status["job_objects"] = "ok"
    except OSError as exc:
        status["job_objects"] = f"kernel32 unavailable: {exc}"
    return status


def _check_linux() -> dict[str, str]:
    status = {}
    if not os.path.isdir("/proc") or not os.path.exists("/proc/self"):
        status["procfs"] = "/proc is not mounted or not readable"
    else:
        status["procfs"] = "ok"
    children = f"/proc/self/task/{os.getpid()}/children"
    try:
        with open(children, "r", encoding="ascii") as stream:
            stream.read(4096)
        status["proc_children"] = "ok"
    except OSError as exc:
        status["proc_children"] = f"{children} unavailable: {exc}"
    native = getattr(os, "pidfd_open", None)
    if native is None:
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            syscall = libc.syscall
            syscall.restype = ctypes.c_long
            # pidfd_open(self, 0) on a live pid returns a valid fd.
            result = syscall(434, os.getpid(), 0)
            if result < 0:
                errno = ctypes.get_errno()
                status["pidfd"] = f"pidfd_open syscall failed (errno {errno})"
            else:
                os.close(result)
                status["pidfd"] = "ok"
        except (OSError, AttributeError) as exc:
            status["pidfd"] = f"pidfd probe failed: {exc}"
    else:
        try:
            fd = native(os.getpid(), 0)
            os.close(fd)
            status["pidfd"] = "ok"
        except OSError as exc:
            status["pidfd"] = f"pidfd_open failed: {exc}"
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.restype = ctypes.c_int
        libc.prctl.argtypes = [ctypes.c_ulong, ctypes.c_void_p,
                               ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        status["subreaper"] = _query_subreaper(libc.prctl)
    except (OSError, AttributeError) as exc:
        status["subreaper"] = f"prctl unavailable: {exc}"
    return status


#: PR_GET_CHILD_SUBREAPER (include/uapi/linux/prctl.h): reads the caller's
#: child-subreaper flag into an int* (second argument); it is NOT 52 -
#: that number is PR_GET_SPECULATION_CTRL with different argument ABI.
PR_GET_CHILD_SUBREAPER = 37


def _query_subreaper(prctl) -> str:
    """Query PR_GET_CHILD_SUBREAPER through the given prctl callable.

    The correct ABI passes an ``int*`` OUT pointer as the second argument;
    the return value is 0 on success and -1 with errno on failure. A
    textual "ok" here means the exact operation was confirmed.
    """
    value = ctypes.c_int(-1)
    result = prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(value),
                   ctypes.c_ulong(0), ctypes.c_ulong(0), ctypes.c_ulong(0))
    if type(result) is not int or result < 0:
        errno = ctypes.get_errno()
        return f"prctl({PR_GET_CHILD_SUBREAPER}) failed (errno {errno})"
    if value.value not in (0, 1):
        return f"unexpected subreaper value {value.value}"
    return "ok"


def containment_preflight(*, platform: str = None) -> dict[str, str]:
    """Passive status map requirement -> 'ok' | diagnostic (never raises)."""
    platform = platform or sys.platform
    if platform == "win32":
        return _check_windows()
    if platform == "linux":
        return _check_linux()
    return {"platform": f"no qualified containment backend on {platform}"}


def require_containment(*, platform: str = None) -> None:
    """Raise the typed preflight error when any requirement is missing.

    C2/R07 + C3/S07: the typed ``code`` is a stable contract
    (``PROCESS_CONTAINMENT_UNAVAILABLE``) for CLI/Server/protocol
    classification; the structured, redacted requirement map travels in
    the separate ``message`` field - never concatenated into the enum.
    """
    status = containment_preflight(platform=platform)
    missing = {name: detail for name, detail in status.items()
               if detail != "ok"}
    if missing:
        detail = "; ".join(f"{name}: {reason}"
                           for name, reason in sorted(missing.items()))
        raise CoreError("PROCESS_CONTAINMENT_UNAVAILABLE", "preflight",
                        retry_safe=True, message=detail)
