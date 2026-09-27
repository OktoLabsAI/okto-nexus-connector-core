"""Extracted owned-process backends; attach targets must never use these."""

from __future__ import annotations

import os
import subprocess

from .birth import observe_recorded_process_birth, snapshot_owned_process_birth
from .preflight import (containment_preflight,
                       containment_requirements, require_containment)
import sys
from typing import Sequence


def spawn_owned_process(argv: Sequence[str], **kwargs) -> subprocess.Popen:
    max_tree_processes = kwargs.pop("max_tree_processes", None)
    if max_tree_processes is not None and (
            type(max_tree_processes) is not int or
            not 1 <= max_tree_processes <= 4096):
        raise ValueError("invalid owned tree process limit")
    if not argv or any(not isinstance(part, str) or not part for part in argv):
        raise ValueError("nonempty structured argv is required")
    if not os.path.isabs(argv[0]):
        raise FileNotFoundError("owned executable must be absolute and locally selected")
    if not os.path.isabs(kwargs.get("cwd") or "") or not isinstance(kwargs.get("env"), dict):
        raise ValueError("owned launch needs local absolute cwd and explicit environment")
    for stream in ("stdin", "stdout", "stderr"):
        kwargs.setdefault(stream, subprocess.PIPE)
        if kwargs.get(stream) != subprocess.PIPE:
            raise ValueError("owned launch requires three separate pipes")
    if kwargs.get("shell") or kwargs.get("preexec_fn"):
        raise ValueError("owned launch forbids shell/preexec")
    options = dict(kwargs)
    if max_tree_processes is not None:
        options["max_tree_processes"] = max_tree_processes
    if os.name == "nt":
        from .windows_process import OwnedWindowsPopen
        return OwnedWindowsPopen(list(argv), **options)
    if sys.platform == "linux":
        from .linux_process import OwnedLinuxPopen
        return OwnedLinuxPopen(list(argv), **options)
    raise RuntimeError("managed process ownership is unqualified on this platform")


def owned_tree_census(process: subprocess.Popen, *,
                      limit: int = 256) -> dict[str, object]:
    """Bounded read-only census of one owned process tree.

    Windows counts the job object's member PIDs (kernel view, includes
    descendants that kept their group). Linux counts the child's live process
    group from /proc; descendants that called setsid escape both this census
    and containment, exactly as documented for kill semantics. This is an
    observation, never authority to signal or adopt a PID.
    """
    census = getattr(process, "owned_tree_pids", None)
    if not callable(census):
        return {"pids": [], "count": 0, "overflow": False,
                "requested_limit": None, "limit_enforced": False,
                "supported": False}
    pids, overflow = census(limit)
    return {"pids": pids, "count": len(pids), "overflow": overflow,
            "requested_limit": getattr(process, "_requested_tree_limit", None),
            "limit_enforced": bool(getattr(process, "_active_process_limit",
                                            False)),
            "supported": True}


def observe_owned_process(process: subprocess.Popen) -> dict[str, object]:
    exit_code = process.poll()
    return {"stop_observed": exit_code is not None
            and bool(getattr(process, "tree_stopped", True)),
            "exit_code": exit_code}
