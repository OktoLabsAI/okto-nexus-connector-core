"""Extracted owned-process backends; attach targets must never use these."""

from __future__ import annotations

import os
import subprocess

from .birth import observe_recorded_process_birth, snapshot_owned_process_birth
import sys
from typing import Sequence


def spawn_owned_process(argv: Sequence[str], **kwargs) -> subprocess.Popen:
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
    if os.name == "nt":
        from .windows_process import OwnedWindowsPopen
        return OwnedWindowsPopen(list(argv), **options)
    if sys.platform == "linux":
        from .linux_process import OwnedLinuxPopen
        return OwnedLinuxPopen(list(argv), **options)
    raise RuntimeError("managed process ownership is unqualified on this platform")


def observe_owned_process(process: subprocess.Popen) -> dict[str, object]:
    exit_code = process.poll()
    return {"stop_observed": exit_code is not None
            and bool(getattr(process, "tree_stopped", True)),
            "exit_code": exit_code}
