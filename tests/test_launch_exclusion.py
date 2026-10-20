"""Real OS primitives, using only disposable child processes owned by tests."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import subprocess
import sys
import uuid

import pytest

from nexus_connector_core.native.process.launch_exclusion import HostLaunchExclusion, LaunchGateBusy


@pytest.mark.skipif(sys.platform not in {'win32', 'linux', 'darwin'}, reason='Unqualified host')
def test_held_producer_does_not_block_siblings_and_is_released_on_exception():
    gate = HostLaunchExclusion()
    producer, sibling = uuid.uuid4().hex, uuid.uuid4().hex
    def attempt(identity):
        with gate.hold(identity):
            return 'acquired'
    with ThreadPoolExecutor(max_workers=1) as worker:
        with pytest.raises(RuntimeError, match='injected'):
            with gate.hold(producer):
                with pytest.raises(LaunchGateBusy):
                    worker.submit(attempt, producer).result(timeout=10)
                assert worker.submit(attempt, sibling).result(timeout=10) == 'acquired'
                raise RuntimeError('injected holder failure')
        assert worker.submit(attempt, producer).result(timeout=10) == 'acquired'


@pytest.mark.skipif(sys.platform not in {'win32', 'linux', 'darwin'}, reason='Unqualified host')
def test_separate_process_cannot_enter_until_original_holder_crashes():
    producer = uuid.uuid4().hex
    retained_mutex = None
    if sys.platform == 'win32':
        # Keep the same OS object alive after the child dies, so the next
        # acquisition exercises WAIT_ABANDONED rather than a recreated mutex.
        import ctypes
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes, kernel.CreateMutexW.restype = [ctypes.c_void_p,w.BOOL,w.LPCWSTR], w.HANDLE
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        retained_mutex = kernel.CreateMutexW(None, False, 'Global\\nexus-core-launch-'+producer)
        assert retained_mutex
    # Use the same package/dependencies as this process, including explicitly
    # selected user-site dependencies when the source campaign uses them.
    search_paths = json.dumps([str(Path(p).resolve()) for p in sys.path if p])
    code = '''import os,sys
import json
sys.path[:] = json.loads(sys.argv[1])
from nexus_connector_core.native.process.launch_exclusion import HostLaunchExclusion
with HostLaunchExclusion().hold(sys.argv[2]):
    print('owned', flush=True)
    sys.stdin.readline()
    os._exit(17)
'''
    child = subprocess.Popen([sys.executable, '-I', '-c', code, search_paths, producer],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    worker = ThreadPoolExecutor(max_workers=1)
    try:
        line = worker.submit(child.stdout.readline).result(timeout=10).strip()
        assert line == 'owned', child.stderr.read() if child.poll() is not None else line
        with pytest.raises(LaunchGateBusy):
            with HostLaunchExclusion().hold(producer):
                pytest.fail('Two processes entered the same launch frontier')
        # The child exits abnormally while it owns the lock. This is not a
        # proof about any harness; it only qualifies OS gate lifetime.
        child.stdin.write('crash\n')
        child.stdin.flush()
        assert child.wait(timeout=10) == 17
        with HostLaunchExclusion().hold(producer):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        worker.shutdown(wait=True)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()
        if retained_mutex is not None:
            assert kernel.CloseHandle(retained_mutex)


@pytest.mark.parametrize('producer', ['', '../other', 'a'*31, 'a'*33, True, None])
def test_invalid_producer_cannot_open_an_os_resource(producer):
    with pytest.raises(ValueError):
        with HostLaunchExclusion().hold(producer):
            pytest.fail('Invalid producer acquired an OS gate')
