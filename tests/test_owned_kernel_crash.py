"""Crash qualification of the kernel around a real owned local LF process."""

import asyncio
import ctypes
import json
import os
import queue
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from nexus_connector_core import ExecutionContext, Operation, OperationKey
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel


PEER = Path(__file__).parent / "fixtures" / "owned_kernel_crash_peer.py"
KEY = OperationKey("owned-server", "owned-executor", "owned-crash-operation")
OPERATION = Operation("owned-crash-operation", "owned-session", "turn.submit",
                      {"text": "local peer"})


def _context():
    return ExecutionContext("owned-server", "owned-executor", "binding",
                            "agent", "workspace", 1, 1, 7,
                            time.monotonic() + 60, frozenset({"turn.submit"}))


def _read_report(owner):
    reports = queue.Queue(maxsize=1)
    threading.Thread(target=lambda: reports.put(owner.stdout.readline()),
                     daemon=True).start()
    try:
        line = reports.get(timeout=20)
    except queue.Empty as exc:
        raise AssertionError("owner did not report its native peer") from exc
    assert line, "owner exited before reporting its native peer"
    return json.loads(line)


@pytest.mark.skipif(not (os.name == "nt" or sys.platform == "linux"),
                    reason="owned process backend is Windows/Linux only")
@pytest.mark.parametrize("boundary,stage,marker_exists", [
    ("before_spawn", "SUBMISSION_STARTED", False),
    ("after_spawn", "SUBMISSION_STARTED", False),
    ("after_partial_write", "SUBMISSION_STARTED", False),
    ("after_write", "SUBMISSION_STARTED", True),
    ("after_receipt", "SUBMITTED", True),
])
def test_crash_at_owned_spawn_write_never_replays_and_reaps_peer(
        tmp_path, boundary, stage, marker_exists):
    db_path = tmp_path / f"{boundary}.db"
    marker = tmp_path / f"{boundary}.effect"
    owner = subprocess.Popen(
        [sys.executable, str(PEER), str(db_path), str(marker), boundary],
        cwd=tmp_path, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    native_handle = None
    kernel = None
    try:
        report = _read_report(owner)
        native_pid = report["native_pid"]
        if native_pid is not None:
            if os.name == "nt":
                from ctypes import wintypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                               wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,
                                                       wintypes.DWORD]
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                native_handle = kernel.OpenProcess(0x00100001, False, native_pid)
                assert native_handle
                assert kernel.WaitForSingleObject(native_handle, 0) == 258
            else:
                from nexus_connector_core.native.process.linux_process_guardian import (
                    pidfd_open, pidfd_send_signal,
                )

                native_handle = pidfd_open(native_pid)
                assert not select.select([native_handle], [], [], 0)[0]

        owner.stdin.write("CRASH\n")
        owner.stdin.flush()
        assert owner.wait(timeout=10) == 91, owner.stderr.read()
        if native_handle is not None:
            if os.name == "nt":
                assert kernel.WaitForSingleObject(native_handle, 10000) == 0
            else:
                assert select.select([native_handle], [], [], 10)[0]

        assert marker.exists() == marker_exists
        if marker_exists:
            assert marker.read_bytes() == b"native-peer-command-once"

        async def inspect():
            journal = SQLiteJournal(db_path)
            try:
                receipt = await journal.get_receipt(KEY)
                assert receipt is not None and receipt.stage == stage
                assert receipt.possible_effect and not receipt.retry_safe
                invoked = False

                async def forbidden_effect():
                    nonlocal invoked
                    invoked = True
                    raise AssertionError("owned process replayed")

                replay = await OperationKernel(journal).execute(
                    OPERATION, _context(), forbidden_effect)
                assert replay == receipt
                assert not invoked
            finally:
                journal.close()

        asyncio.run(inspect())
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)
        if native_handle is not None:
            if os.name == "nt":
                if kernel.WaitForSingleObject(native_handle, 0) != 0:
                    kernel.TerminateProcess(native_handle, 1)
                kernel.CloseHandle(native_handle)
            else:
                try:
                    pidfd_send_signal(native_handle, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.close(native_handle)
        for pipe in (owner.stdin, owner.stdout, owner.stderr):
            if pipe:
                pipe.close()
