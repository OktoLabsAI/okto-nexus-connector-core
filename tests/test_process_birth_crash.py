"""Abrupt Core-owner death after spawn but before birth registration."""

import asyncio
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading

import pytest

from nexus_connector_core import OperationKey, SessionKey
from nexus_connector_core.journal import SQLiteJournal


KEY = OperationKey("birth-crash-server", "birth-crash-executor",
                   "birth-crash-open")
SESSION = SessionKey(KEY.server_id, KEY.executor_id, "birth-crash-session")
INTENT = "sha256:" + "b" * 64


@pytest.mark.skipif(not (os.name == "nt" or sys.platform == "linux"),
                    reason="Core containment is qualified only on Windows/Linux")
def test_owner_crash_between_spawn_and_birth_record(tmp_path: Path):
    path = tmp_path / "spawn-before-birth.db"
    owner_code = (
        "import asyncio,json,os,sys,time\n"
        "from nexus_connector_core import OperationKey\n"
        "from nexus_connector_core.journal import SQLiteJournal\n"
        "from nexus_connector_core.native.process import spawn_owned_process\n"
        "async def run():\n"
        " j=SQLiteJournal(sys.argv[1])\n"
        " k=OperationKey('birth-crash-server','birth-crash-executor','birth-crash-open')\n"
        " await j.admit(k,'sha256:'+'b'*64,'birth-crash-session',"
        "effect_imminent=True,claim_session=True,"
        "connection_generation=3,session_owner_generation=1)\n"
        " p=spawn_owned_process((sys.executable,'-c','import time;time.sleep(60)'),"
        "cwd=os.getcwd(),env=dict(os.environ))\n"
        " print(json.dumps({'pid':p.pid}),flush=True)\n"
        " time.sleep(60)\n"
        "asyncio.run(run())\n"
    )
    owner_env = dict(os.environ)
    source = str(Path(__file__).resolve().parents[1] / "src")
    owner_env["PYTHONPATH"] = os.pathsep.join(
        item for item in (source, owner_env.get("PYTHONPATH", "")) if item)
    owner = subprocess.Popen([sys.executable, "-c", owner_code, str(path)],
                             cwd=tmp_path, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=owner_env)
    handle = None
    pidfd = None
    kernel = None
    pid = None
    try:
        lines = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: lines.put(owner.stdout.readline()),
                         daemon=True).start()
        try:
            line = lines.get(timeout=15)
        except queue.Empty:
            pytest.fail("owner did not report the contained child")
        assert line, owner.stderr.read() if owner.poll() is not None else ""
        pid = json.loads(line)["pid"]
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                           wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,
                                                    wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            handle = kernel.OpenProcess(0x00100001, False, pid)
            assert handle
            assert kernel.WaitForSingleObject(handle, 0) == 0x102
        else:
            import select
            from nexus_connector_core.native.process.linux_process_guardian import (
                pidfd_open,
            )

            pidfd = pidfd_open(pid)
            assert not select.select([pidfd], [], [], 0)[0]

        owner.kill()
        owner.wait(timeout=10)
        if handle is not None:
            assert kernel.WaitForSingleObject(handle, 10_000) == 0
        else:
            assert select.select([pidfd], [], [], 10)[0]

        async def inspect():
            journal = SQLiteJournal(path)
            try:
                receipt = await journal.get_receipt(KEY)
                assert receipt is not None
                assert receipt.stage == "SUBMISSION_STARTED"
                assert receipt.possible_effect is True
                claim = (await journal.claimed_sessions(
                    KEY.server_id, KEY.executor_id)).claims[0]
                assert claim.opening_connection_generation == 3
                assert claim.opening_owner_generation == 1
                assert await journal.get_process_birth(SESSION) is None
                replay, fresh = await journal.admit(
                    KEY, INTENT, SESSION.session_id, claim_session=True,
                    connection_generation=3, session_owner_generation=1)
                assert not fresh and replay == receipt
            finally:
                journal.close()

        asyncio.run(inspect())
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)
        if handle is not None:
            if kernel.WaitForSingleObject(handle, 0) != 0:
                kernel.TerminateProcess(handle, 1)
            kernel.CloseHandle(handle)
        if pidfd is not None:
            from nexus_connector_core.native.process.linux_process_guardian import (
                pidfd_send_signal,
            )

            try:
                pidfd_send_signal(pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(pidfd)
        for pipe in (owner.stdout, owner.stderr):
            if pipe:
                pipe.close()
