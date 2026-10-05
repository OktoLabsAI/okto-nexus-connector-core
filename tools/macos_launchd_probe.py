"""Explicit native launchd/SCM_RIGHTS experiment; never a runtime backend.

Run with --run-native on macOS. Only fixed Python fixtures execute. No provider,
credentials or sudo are used. Each fixture is bounded; every job is booted out
in the caller's finally block. This does not qualify arbitrary-tree cleanup.
"""
from __future__ import annotations

import argparse
import array
import contextlib
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import secrets
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time


class CoalitionInfo(ctypes.Structure):
    # XNU bsd/sys/proc_info_private.h and osfmk/mach/coalition.h:
    # resource=0, jetsam=1, followed by three reserved uint64_t values.
    _fields_ = [('ids', ctypes.c_uint64 * 2), ('reserved', ctypes.c_uint64 * 3)]


def coalition_of(lib, pid):
    info = CoalitionInfo()
    count = lib.proc_pidinfo(pid, 20, 0, ctypes.byref(info), ctypes.sizeof(info))
    if count != ctypes.sizeof(info):
        raise OSError(ctypes.get_errno() or errno.EIO,
                      f'Coalition ABI response {count}, expected {ctypes.sizeof(info)}')
    value = tuple(info.ids)
    if not all(value):
        raise ValueError('A nonzero resource and jetsam coalition are required')
    return value


def primitives():
    path = Path(__file__).with_name('macos_containment_probe.py')
    spec = importlib.util.spec_from_file_location('macos_probe_primitives', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def job_plist(label, config, stdout, stderr):
    return dict(Label=label, ProgramArguments=[str(Path(sys.executable).resolve()), '-I',
                str(Path(__file__).resolve()), '--guardian', str(config)],
                RunAtLoad=True, KeepAlive=False, ProcessType='Background',
                StandardOutPath=str(stdout), StandardErrorPath=str(stderr))


def launchctl(*args, timeout=8):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True,
                          text=True, timeout=timeout, close_fds=True)


def send_pipes(connection, token, native_pid, descriptors):
    payload = json.dumps(dict(token=token, native_pid=native_pid)).encode() + b'\n'
    fds = array.array('i', descriptors)
    sent = connection.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds)])
    if sent != len(payload):
        raise OSError('Incomplete descriptor handoff')


def receive_pipes(connection, token):
    """Close every received descriptor on malformed/truncated handoff."""
    fds = []
    try:
        size = array.array('i').itemsize
        data, ancillary, flags, _ = connection.recvmsg(4096, socket.CMSG_SPACE(16 * size))
        unexpected = False
        for level, kind, payload in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                unexpected = True
                continue
            received = array.array('i')
            received.frombytes(payload[:len(payload) - len(payload) % size])
            fds.extend(received)
            if len(payload) % size:
                unexpected = True
        if flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC) or unexpected:
            raise ValueError('Truncated or unexpected descriptor handoff')
        # AF_UNIX SOCK_STREAM can split the normal data even when descriptors
        # arrive together. Read a bounded line before validating its metadata.
        while not data.endswith(b'\n') and len(data) < 4096:
            part = connection.recv(4096 - len(data))
            if not part:
                break
            data += part
        metadata = json.loads(data)
        if (len(fds) != 3 or metadata.get('token') != token or
                type(metadata.get('native_pid')) is not int or metadata['native_pid'] <= 1):
            raise ValueError('Invalid descriptor handoff identity or count')
        for fd in fds:
            os.set_inheritable(fd, False)
        return metadata['native_pid'], fds
    except BaseException:
        for fd in fds:
            with contextlib.suppress(OSError):
                os.close(fd)
        raise


FIXTURE = r'''
import json, os, signal, sys, time
signal.alarm(15)
def extras():
    result=[]
    for fd in range(3,256):
        try: os.fstat(fd)
        except OSError: continue
        result.append(fd)
    return result
print(json.dumps(dict(kind='leader',pid=os.getpid(),extra_fds=extras())),flush=True)
child=os.fork()
if child == 0:
    signal.alarm(10)
    print(json.dumps(dict(kind='grandchild',pid=os.getpid(),extra_fds=extras())),flush=True)
    os._exit(0)
os.waitpid(child,0)
message=sys.stdin.readline()
print(json.dumps(dict(kind='echo',message=message.rstrip('\n'))),flush=True)
print('native-stderr-marker',file=sys.stderr,flush=True)
while True: time.sleep(.05)
'''


def guardian(config_path):
    if sys.platform != 'darwin':
        raise RuntimeError('The launchd guardian experiment requires native macOS')
    config = json.loads(Path(config_path).read_text())
    p = primitives()
    lib = p._libproc()
    report = dict(containment_qualified=False, tree_stop_proven=False,
                  pid=os.getpid(), coalition_abi_size=ctypes.sizeof(CoalitionInfo))
    native = None
    native_birth = None
    connection = None
    watcher = None
    start = time.monotonic()
    try:
        own = coalition_of(lib, os.getpid())
        caller = tuple(config['caller_coalition'])
        launchd = coalition_of(lib, 1)
        report.update(coalition=list(own), caller_coalition=list(caller), launchd_coalition=list(launchd))
        # Reject sharing either type, not merely equality of both IDs together.
        if any(own[index] in (caller[index], launchd[index]) for index in (0, 1)):
            raise RuntimeError('Guardian coalition shares a type with caller or launchd')
        owner_pid = config['owner_pid']
        if p.identity(owner_pid)['birth'] != config['owner_birth']:
            raise RuntimeError('Owner birth changed before watch registration')
        watcher = select.kqueue()
        watcher.control([select.kevent(owner_pid, filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_EXIT)], 0, 0)
        if p.identity(owner_pid)['birth'] != config['owner_birth'] or watcher.control(None, 1, 0):
            raise RuntimeError('Owner exited before fixture launch')
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(5)
        connection.connect(config['socket'])
        if p.identity(owner_pid)['birth'] != config['owner_birth'] or watcher.control(None, 1, 0):
            raise RuntimeError('Owner exited during control-channel connection')
        native = subprocess.Popen([str(Path(sys.executable).resolve()), '-I', '-c', FIXTURE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, start_new_session=True)
        native_birth = p.identity(native.pid)['birth']
        report['native_pid'] = native.pid
        report['native_birth'] = native_birth
        if coalition_of(lib, native.pid) != own:
            raise RuntimeError('Native fixture did not inherit the job coalition')
        send_pipes(connection, config['token'], native.pid,
                   [native.stdin.fileno(), native.stdout.fileno(), native.stderr.fileno()])
        for stream in (native.stdin, native.stdout, native.stderr):
            stream.close()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if watcher.control(None, 1, 0):
                report['stop_trigger'] = 'owner_exit'
                break
            readable, _, _ = select.select([connection], [], [], .02)
            if readable:
                request = connection.recv(1)
                report['stop_trigger'] = 'control_eof' if not request else 'cancel'
                break
            if native.poll() is not None:
                report['stop_trigger'] = 'fixture_exit'
                break
        else:
            report['stop_trigger'] = 'deadline'
        report['trigger_elapsed_seconds'] = round(time.monotonic() - start, 6)
    except BaseException as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        cleanup_started = time.monotonic()
        if native is not None:
            try:
                # This fixed fixture reaps its one child before echoing. This
                # cleanup is not offered as arbitrary coalition-tree cleanup.
                if native.poll() is None:
                    if native_birth is None or p.identity(native.pid)['birth'] != native_birth:
                        raise RuntimeError('Cannot verify native fixture birth for cleanup')
                    if coalition_of(lib, native.pid) != coalition_of(lib, os.getpid()):
                        raise RuntimeError('Native fixture coalition changed during cleanup')
                    native.terminate()
                    try:
                        native.wait(timeout=.5)
                    except subprocess.TimeoutExpired:
                        # Unreaped direct child still belongs to this Popen.
                        native.kill()
                        native.wait(timeout=3)
                report['native_fixture_reaped'] = native.returncode is not None
                report['native_returncode'] = native.returncode
            except BaseException as exc:
                report['cleanup_error'] = f'{type(exc).__name__}: {exc}'
        if connection is not None:
            connection.close()
        if watcher is not None:
            watcher.close()
        report['cleanup_seconds'] = round(time.monotonic() - cleanup_started, 6)
        report_path = Path(config['report'])
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(report_path)
    return 1 if 'error' in report or 'cleanup_error' in report else 0


def read_lines(fd, count, timeout=5):
    data = b''
    deadline = time.monotonic() + timeout
    while data.count(b'\n') < count and len(data) < 16384:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError('Native pipe response deadline exceeded')
        part = os.read(fd, 4096)
        if not part:
            raise EOFError('Native pipe closed before the expected response')
        data += part
    if data.count(b'\n') != count:
        raise ValueError('Unexpected native pipe response framing')
    return data.decode().splitlines()


def scenario(domain, mode):
    p = primitives()
    label = f'ai.oktolabs.nexus-pipes-probe.{os.getpid()}.{secrets.token_hex(6)}'
    service = domain + '/' + label
    result = dict(domain=domain, mode=mode, label=label, containment_qualified=False)
    descriptors = []
    connection = None
    owner = None
    # Keep the AF_UNIX path short; the usual macOS temp directory is too long.
    with tempfile.TemporaryDirectory(prefix='nxpipe-', dir='/tmp') as directory:
        root = Path(directory)
        os.chmod(root, 0o700)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.settimeout(8)
        listener.bind(str(root / 'control.sock'))
        listener.listen(1)
        report_path = root / 'guardian.json'
        try:
            # A separate owner permits SIGKILL while this observer retains the
            # control socket, proving that cleanup does not depend on its EOF.
            owner = subprocess.Popen([str(Path(sys.executable).resolve()), '-I', '-c',
                'import signal,time; signal.alarm(40); time.sleep(35)'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True)
            config = dict(socket=str(root / 'control.sock'), token=secrets.token_hex(32),
                report=str(report_path), owner_pid=owner.pid, owner_birth=p.identity(owner.pid)['birth'],
                caller_coalition=list(coalition_of(p._libproc(), os.getpid())))
            config_path = root / 'config.json'
            config_path.write_text(json.dumps(config))
            plist_path = root / 'job.plist'
            plist_path.write_bytes(plistlib.dumps(job_plist(label, config_path, root / 'stdout', root / 'stderr')))
            boot = launchctl('bootstrap', domain, str(plist_path))
            result['bootstrap'] = dict(returncode=boot.returncode, stderr=boot.stderr[-4096:])
            if boot.returncode:
                raise RuntimeError('launchctl bootstrap refused the requested domain')
            connection, _ = listener.accept()
            connection.settimeout(5)
            native_pid, descriptors = receive_pipes(connection, config['token'])
            result['native_pid'] = native_pid
            os.write(descriptors[0], b'nexus-native-pipe-check\n')
            frames = [json.loads(line) for line in read_lines(descriptors[1], 3)]
            stderr = read_lines(descriptors[2], 1)
            by_kind = {frame['kind']: frame for frame in frames}
            result['pipes'] = dict(frames=frames, stderr=stderr,
                round_trip=by_kind.get('echo', {}).get('message') == 'nexus-native-pipe-check',
                descriptor_hygiene=all(by_kind.get(kind, {}).get('extra_fds') == [] for kind in ('leader', 'grandchild')),
                received_fds_noninheritable=all(not os.get_inheritable(fd) for fd in descriptors))
            trigger_time = time.monotonic()
            if mode == 'owner_exit':
                owner.kill()
                owner.wait(timeout=3)
            elif mode == 'control_eof':
                connection.close()
                connection = None
            else:
                connection.sendall(b'C')
            deadline = time.monotonic() + 6
            while not report_path.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            if not report_path.exists():
                raise TimeoutError('Guardian did not produce a cleanup report')
            # Report publication is atomic. Retain the bounded retry for a
            # transient external reader/writer or filesystem anomaly.
            while True:
                try:
                    result['guardian'] = json.loads(report_path.read_text())
                    break
                except json.JSONDecodeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.01)
            result['observed_cleanup_latency_seconds'] = round(time.monotonic() - trigger_time, 6)
            result['status'] = 'OBSERVED' if (result['pipes']['round_trip'] and
                result['pipes']['descriptor_hygiene'] and result['pipes']['received_fds_noninheritable'] and
                result['guardian'].get('stop_trigger') == mode and
                result['guardian'].get('native_fixture_reaped') is True and
                'error' not in result['guardian'] and 'cleanup_error' not in result['guardian']) else 'FAILED'
        except Exception as exc:
            result.update(status='FAILED', error=f'{type(exc).__name__}: {exc}')
        finally:
            if connection is not None:
                connection.close()
            for fd in descriptors:
                with contextlib.suppress(OSError):
                    os.close(fd)
            listener.close()
            if owner is not None:
                if owner.poll() is None:
                    owner.kill()
                owner.wait(timeout=3)
            # Give the guardian time to react to owner exit/control EOF before
            # bootout; early bootout alone is not native-process cleanup.
            if 'guardian' not in result:
                until = time.monotonic() + 5
                while not report_path.exists() and time.monotonic() < until:
                    time.sleep(.05)
                with contextlib.suppress(OSError, json.JSONDecodeError):
                    result['guardian'] = json.loads(report_path.read_text())
            try:
                removed = launchctl('bootout', service)
                result['bootout_returncode'] = removed.returncode
                registered = launchctl('print', service)
                result['post_bootout_print'] = dict(returncode=registered.returncode,
                                                   stderr=registered.stderr[-4096:])
                result['label_left_registered'] = (True if registered.returncode == 0 else
                                                   False if removed.returncode == 0 else None)
                # A failed read alone cannot distinguish absence from lost
                # permission/domain access; require acknowledged bootout too.
                if result['label_left_registered'] is not False:
                    result['status'] = 'FAILED'
            except subprocess.TimeoutExpired:
                result.update(status='FAILED', label_left_registered=None, cleanup_error='launchctl cleanup timed out')
            for name in ('stdout', 'stderr'):
                path = root / name
                if path.exists():
                    result['guardian_' + name] = path.read_text(errors='replace')[-4096:]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-native', action='store_true')
    parser.add_argument('--domain', choices=('user', 'gui'), default='user')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--guardian', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.guardian:
        return guardian(args.guardian)
    if not args.run_native:
        parser.error('--run-native is required')
    report = dict(schema_version=1, platform=sys.platform, machine=platform.machine(),
        python=platform.python_version(), macos=platform.mac_ver()[0],
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        containment_qualified=False, provider_execution=False, tree_stop_proven=False)
    if sys.platform != 'darwin':
        report.update(status='UNSUPPORTED_TEST_HOST', reason='Run on native macOS')
    else:
        domain = f'{args.domain}/{os.getuid()}'
        report['scenarios'] = []
        try:
            for mode in ('cancel', 'owner_exit', 'control_eof'):
                report['scenarios'].append(scenario(domain, mode))
            report['status'] = 'PRIMITIVES_OBSERVED' if all(item['status'] == 'OBSERVED' for item in report['scenarios']) else 'FAILED'
        except KeyboardInterrupt:
            report['status'] = 'INTERRUPTED'
    value = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(value, encoding='utf-8')
    print(value, end='')
    return 0 if report['status'] == 'PRIMITIVES_OBSERVED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
