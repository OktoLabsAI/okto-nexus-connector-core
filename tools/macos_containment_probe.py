"""Native feasibility evidence, not a containment backend or qualification.

Only --run-native creates a short-lived Python fixture. No provider or shell
is executed. Run with Python 3.11+ on the target Mac; no dependencies required.
ABI source: Apple XNU bsd/sys/proc_info.h (PROC_PIDTBSDINFO).
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import subprocess
import sys
import tempfile
import time


class BsdInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
        'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in (
        'nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64),
                ('start_usec', ctypes.c_uint64)]


def identity(pid: int) -> dict:
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    query = lib.proc_pidinfo
    query.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                      ctypes.c_void_p, ctypes.c_int]
    query.restype = ctypes.c_int
    info = BsdInfo()
    count = query(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if count != ctypes.sizeof(info) or info.pid != pid:
        raise RuntimeError(f'proc_pidinfo: bytes={count}, errno={ctypes.get_errno()}')
    if info.start_sec <= 0 or info.start_usec >= 1_000_000:
        raise RuntimeError('Invalid process birth timestamp')
    return dict(pid=info.pid, ppid=info.ppid, pgid=info.pgid,
                birth=[info.start_sec, info.start_usec], abi_size=count)


def boot_session() -> str:
    lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    query = lib.sysctlbyname
    query.argtypes = [ctypes.c_char_p, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p,
                      ctypes.c_size_t]
    query.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    size = ctypes.c_size_t(len(buffer))
    if query(b'kern.bootsessionuuid', buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot read boot session identity')
    value = buffer.value.decode('ascii')
    if not value:
        raise RuntimeError('Empty boot session identity')
    # Report stability without exposing a host boot identifier.
    return hashlib.sha256(value.encode()).hexdigest()


FIXTURE = '''import os, select, signal, sys
signal.alarm(12)
if not select.select([sys.stdin], [], [], 8)[0]:
    raise SystemExit(2)
if os.read(0, 1) != b"G":
    raise SystemExit(3)
child = os.fork()
if child == 0:
    os._exit(0)
os.waitpid(child, 0)
'''


def native_checks() -> dict:
    before = identity(os.getpid())
    after = identity(os.getpid())
    if before != after:
        raise RuntimeError('Self birth identity changed across reads')
    boot = boot_session()
    if boot_session() != boot:
        raise RuntimeError('Boot identity changed across reads')
    with select.kqueue() as queue, tempfile.TemporaryDirectory(prefix='nexus-mac-probe-') as cwd:
        proc = subprocess.Popen([sys.executable, '-I', '-c', FIXTURE],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, env={},
                                close_fds=True, start_new_session=True)
        try:
            child_birth = identity(proc.pid)
            if child_birth['pgid'] != proc.pid or child_birth['ppid'] != os.getpid():
                raise RuntimeError('Fixture was not born in its private process group')
            queue.control([select.kevent(proc.pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_EXIT | select.KQ_NOTE_FORK)], 0, 0)
            proc.stdin.write(b'G')
            proc.stdin.flush()
            events = []
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                for event in queue.control(None, 8, min(.5, max(0, deadline-time.monotonic()))):
                    if event.flags & select.KQ_EV_ERROR:
                        raise RuntimeError(f'kevent error: {event.data}')
                    events.append(dict(ident=event.ident, filter=event.filter,
                                       flags=event.flags, fflags=event.fflags,
                                       data=event.data))
                if any(e['ident'] == proc.pid and e['fflags'] & select.KQ_NOTE_EXIT for e in events):
                    break
            stdout, stderr = proc.communicate(timeout=3)
            if proc.returncode != 0 or stdout or stderr:
                raise RuntimeError(f'Fixture failed: exit={proc.returncode}')
            observed = lambda flag: any(e['ident'] == proc.pid and e['fflags'] & flag for e in events)
            if not observed(select.KQ_NOTE_EXIT) or not observed(select.KQ_NOTE_FORK):
                raise RuntimeError(f'Expected fork/exit observations missing: {events}')
            return dict(self_identity=before, child_identity=child_birth,
                        boot_identity_sha256=boot, events=events,
                        private_process_group=True, fixture_reaped=True)
        finally:
            # This fixture forks only an immediately exiting, waited child.
            # Never signal a census-discovered PID or claim arbitrary tree cleanup.
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=3)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-native', action='store_true', required=True,
                        help='Explicitly run the bounded synthetic Python fixture')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = dict(schema_version=1, platform=sys.platform,
                  machine=platform.machine(), python=platform.python_version(),
                  macos=platform.mac_ver()[0],
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  containment_qualified=False, provider_execution=False,
                  status='NOT_RUN')
    if sys.platform != 'darwin':
        report.update(status='UNSUPPORTED_TEST_HOST', reason='Run on native macOS')
        code = 2
    else:
        try:
            report.update(checks=native_checks(), status='PRIMITIVES_OBSERVED')
            code = 0
        except Exception as exc:
            report.update(status='FAILED', error=f'{type(exc).__name__}: {exc}')
            code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
