import os
import json
import select
import signal
import subprocess
import sys

import pytest

from nexus_connector_core.native.process import observe_owned_process, spawn_owned_process


@pytest.mark.skipif(not (os.name == "nt" or sys.platform == "linux"),
                    reason="backend is qualified only on Windows/Linux")
def test_owned_process_handle_terminates_own_child(tmp_path):
    process = spawn_owned_process(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        cwd=str(tmp_path), env=dict(os.environ))
    try:
        assert process.poll() is None
        process.kill()
        process.wait(timeout=10)
        assert observe_owned_process(process)["stop_observed"] is True
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe:
                pipe.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_explicit_job_force_reaps_owned_grandchild(tmp_path):
    import ctypes
    import queue
    import threading
    from ctypes import wintypes

    native_code = (
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        "print(json.dumps([os.getpid(),child.pid]),flush=True)\n"
        "time.sleep(60)\n"
    )
    process = spawn_owned_process((sys.executable, "-c", native_code),
                                  cwd=str(tmp_path), env=dict(os.environ))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handles = []
    try:
        lines = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: lines.put(process.stdout.readline()),
                         daemon=True).start()
        line = lines.get(timeout=10)
        assert line, "owned process did not report its tree"
        pids = json.loads(line)
        for pid in pids:
            handle = kernel.OpenProcess(0x00100001, False, pid)
            assert handle
            handles.append(handle)
            assert kernel.WaitForSingleObject(handle, 0) == 258
        process.kill()
        process.wait(timeout=10)
        assert observe_owned_process(process)["stop_observed"] is True
        for handle in handles:
            assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 0) != 0:
                kernel.TerminateProcess(handle, 1)
            kernel.CloseHandle(handle)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe:
                pipe.close()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd guardian contract")
def test_explicit_guardian_force_reaps_escaped_grandchild(tmp_path):
    from nexus_connector_core.native.process.linux_process_guardian import (
        pidfd_open, pidfd_send_signal,
    )

    native_code = (
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "start_new_session=True)\n"
        "print(json.dumps([os.getpid(),child.pid]),flush=True)\n"
        "time.sleep(60)\n"
    )
    process = spawn_owned_process((sys.executable, "-c", native_code),
                                  cwd=str(tmp_path), env=dict(os.environ))
    descriptors = []
    try:
        readable, _, _ = select.select([process.stdout], [], [], 10)
        assert readable, "owned process did not report its tree"
        native_pid, grandchild_pid = json.loads(process.stdout.readline())
        for pid in (process.pid, native_pid, grandchild_pid):
            descriptor = pidfd_open(pid)
            descriptors.append(descriptor)
            assert not select.select([descriptor], [], [], 0)[0]
        process.kill()
        process.wait(timeout=10)
        assert observe_owned_process(process)["stop_observed"] is True
        for descriptor in descriptors:
            assert select.select([descriptor], [], [], 10)[0]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for descriptor in descriptors:
            try:
                pidfd_send_signal(descriptor, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(descriptor)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe:
                pipe.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_abrupt_owner_exit_reaps_child_and_grandchild(tmp_path):
    # Adapted from Nexus tests/test_runtime_process_ownership.py:137-178.
    import ctypes
    from ctypes import wintypes

    child_code = (
        "import subprocess,sys,os,time,json\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        "print(json.dumps([os.getpid(),child.pid]),flush=True)\n"
        "time.sleep(60)\n"
    )
    owner_code = (
        "import os,subprocess,sys,time\n"
        "from nexus_connector_core.native.process import spawn_owned_process\n"
        "p=spawn_owned_process([sys.executable,'-c',sys.argv[1]],"
        "cwd=os.getcwd(),env=dict(os.environ))\n"
        "print(p.stdout.readline().decode(),flush=True)\n"
        "time.sleep(60)\n"
    )
    owner = subprocess.Popen([sys.executable, "-c", owner_code, child_code],
                             cwd=tmp_path, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handles = []
    try:
        line = owner.stdout.readline()
        assert line, "owned Linux process exited before reporting its tree"
        pids = json.loads(line)
        for pid in pids:
            handle = kernel.OpenProcess(0x00100001, False, pid)
            assert handle
            handles.append(handle)
            assert kernel.WaitForSingleObject(handle, 0) == 258
        owner.kill()
        owner.wait(timeout=5)
        for handle in handles:
            assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 0) != 0:
                kernel.TerminateProcess(handle, 1)
            kernel.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd guardian contract")
def test_linux_abrupt_owner_exit_reaps_native_tree(tmp_path):
    from nexus_connector_core.native.process.linux_process_guardian import (
        pidfd_open, pidfd_send_signal,
    )

    native_code = (
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "start_new_session=True)\n"
        "print(json.dumps([os.getpid(),child.pid]),flush=True)\n"
        "time.sleep(60)\n"
    )
    owner_code = (
        "import json,os,subprocess,sys,time\n"
        "from nexus_connector_core.native.process import spawn_owned_process\n"
        "p=spawn_owned_process([sys.executable,'-c',sys.argv[1]],"
        "cwd=os.getcwd(),env=dict(os.environ))\n"
        "print(json.dumps([p.pid,*json.loads(p.stdout.readline())]),flush=True)\n"
        "time.sleep(60)\n"
    )
    owner = subprocess.Popen([sys.executable, "-c", owner_code, native_code],
                             cwd=tmp_path, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    descriptors = []
    try:
        readable, _, _ = select.select([owner.stdout], [], [], 10)
        assert readable, "owned Linux process did not report its tree"
        line = owner.stdout.readline()
        assert line, owner.stderr.read()
        guardian_pid, native_pid, grandchild_pid = json.loads(line)
        for pid in (guardian_pid, native_pid, grandchild_pid):
            descriptor = pidfd_open(pid)
            assert not select.select([descriptor], [], [], 0)[0]
            descriptors.append(descriptor)
        owner.kill()
        owner.wait(timeout=5)
        for descriptor in descriptors:
            assert select.select([descriptor], [], [], 10)[0], (
                "Linux guardian left an owned process alive after owner death")
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        for descriptor in descriptors:
            try:
                pidfd_send_signal(descriptor, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(descriptor)
        for pipe in (owner.stdin, owner.stdout, owner.stderr):
            if pipe:
                pipe.close()
