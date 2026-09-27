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
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            status["job_objects"] = (
                f"CreateJobObjectW failed (WinError {ctypes.get_last_error()})")
        else:
            kernel.CloseHandle(job)
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
        # PR_GET_CHILD_SUBREAPER (52): read-only query.
        if libc.prctl(52, 0, 0, 0, 0) < 0:
            status["subreaper"] = (
                f"prctl query failed (errno {ctypes.get_errno()})")
        else:
            status["subreaper"] = "ok"
    except (OSError, AttributeError) as exc:
        status["subreaper"] = f"prctl unavailable: {exc}"
    return status


def containment_preflight(*, platform: str = None) -> dict[str, str]:
    """Passive status map requirement -> 'ok' | diagnostic (never raises)."""
    platform = platform or sys.platform
    if platform == "win32":
        return _check_windows()
    if platform == "linux":
        return _check_linux()
    return {"platform": f"no qualified containment backend on {platform}"}


def require_containment(*, platform: str = None) -> None:
    """Raise the typed preflight error when any requirement is missing."""
    status = containment_preflight(platform=platform)
    missing = {name: detail for name, detail in status.items()
               if detail != "ok"}
    if missing:
        detail = "; ".join(f"{name}: {reason}"
                           for name, reason in sorted(missing.items()))
        raise CoreError("PROCESS_CONTAINMENT_UNAVAILABLE", "preflight",
                        retry_safe=True)
