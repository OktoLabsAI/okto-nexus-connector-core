"""Owned-tree census and the kernel-enforced per-tree process limit."""

import os
import subprocess
import sys
import time

import pytest

from nexus_connector_core.native.process import (
    owned_tree_census, spawn_owned_process,
)

_WINDOWS = sys.platform == "win32"
_LINUX = sys.platform == "linux"


def _environment() -> dict[str, str]:
    names = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH",
             "TEMP", "TMP"}
    return {name: value for name, value in os.environ.items()
            if name in names}


_SPAWNER = """
import subprocess, sys, time
ok = 0
children = []
for _ in range(5):
    try:
        children.append(subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(20)"]))
        ok += 1
    except OSError:
        pass
print(ok, flush=True)
time.sleep(20)
"""


@pytest.mark.skipif(not _WINDOWS, reason="job-object limit is Windows-only")
def test_windows_active_process_limit_is_kernel_enforced(tmp_path):
    workdir = tmp_path.resolve()
    proc = spawn_owned_process(
        [sys.executable, "-c", _SPAWNER],
        cwd=str(workdir), env=_environment(), max_tree_processes=3)
    try:
        spawned = int(proc.stdout.readline().decode("ascii").strip())
        # The job counts the leader itself: with a limit of three, at most
        # two children can be created before CreateProcess starts failing.
        assert spawned <= 2, spawned
        census = owned_tree_census(proc)
        assert census["supported"] and census["limit_enforced"]
        assert census["requested_limit"] == 3
        assert census["count"] >= 1 and proc.pid in census["pids"]
        assert not census["overflow"]
    finally:
        proc.terminate()
        proc.wait(timeout=15)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if owned_tree_census(proc)["count"] == 0:
            break
        time.sleep(0.05)
    assert owned_tree_census(proc)["count"] == 0


@pytest.mark.skipif(not _WINDOWS, reason="job-object census is Windows-only")
def test_windows_unlimited_tree_reports_enforced_false(tmp_path):
    proc = spawn_owned_process(
        [sys.executable, "-c", "import time; time.sleep(8)"],
        cwd=str(tmp_path.resolve()), env=_environment())
    try:
        census = owned_tree_census(proc)
        assert census["supported"] and not census["limit_enforced"]
        assert census["requested_limit"] is None
        assert census["count"] == 1 and census["pids"] == [proc.pid]
    finally:
        proc.terminate()
        proc.wait(timeout=15)


@pytest.mark.skipif(not _LINUX, reason="process-group census is Linux-only")
def test_linux_group_census_counts_descendants_without_kernel_limit(tmp_path):
    proc = spawn_owned_process(
        [sys.executable, "-c", _SPAWNER],
        cwd=str(tmp_path.resolve()), env=_environment(),
        max_tree_processes=3)
    try:
        spawned = int(proc.stdout.readline().decode("ascii").strip())
        # Linux has no kernel-enforced active-process limit here: all five
        # children spawn, and the requested limit is reported as unenforced
        # rather than silently dropped.
        assert spawned == 5, spawned
        census = owned_tree_census(proc)
        assert census["supported"] and not census["limit_enforced"]
        assert census["requested_limit"] == 3
        assert census["count"] == 7  # guardian + native leader + 5 children
        assert proc.pid in census["pids"]
    finally:
        proc.terminate()
        proc.wait(timeout=20)
    assert owned_tree_census(proc)["count"] == 0


def test_census_reports_unsupported_backends():
    plain = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    plain.wait(timeout=15)
    census = owned_tree_census(plain)
    assert census == {"pids": [], "count": 0, "overflow": False,
                      "requested_limit": None, "limit_enforced": False,
                      "supported": False}


@pytest.mark.parametrize("invalid", [0, -1, True, "3", 1.5, 5000])
def test_invalid_tree_limits_are_refused_before_spawn(tmp_path, invalid):
    with pytest.raises(ValueError):
        spawn_owned_process(
            [sys.executable, "-c", "pass"],
            cwd=str(tmp_path.resolve()), env=_environment(),
            max_tree_processes=invalid)
