"""Native macOS acceptance harness for the launchd-coalition backend.

Exercises the production backend (``nexus_connector_core.native.process``
on darwin) exactly as the runtime uses it. This is the acceptance item 6
campaign from ``plans/MACOS_INTEL_IMPLEMENTATION.md``: fast
double-fork/setsid escapes with zero leaks, owner SIGKILL, cancellation
escalation, descriptor hygiene, shared-coalition refusal, 64-child
census/overflow, PID churn during stop, SIGSTOP races, normal-exit
drainage and 32-slot retention until proven stop.

Only fixed Python fixtures execute; no provider, credential, workspace or
system service is used beyond the per-session launchd job itself. Every
owned launch is expected to end with a proven stop (proof ``D``) and a
deregistered job label. Reports always state the qualification scope.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

DOUBLE_FORK_ESCAPE = r'''
import os, time, json
def escape():
    first = os.fork()
    if first > 0:
        os.waitpid(first, 0)
        return None
    second = os.fork()
    if second > 0:
        os._exit(0)
    os.setsid()
    return os.getpid()
orphan = escape()
print(json.dumps(dict(kind="orphan" if orphan else "leader", pid=os.getpid())), flush=True)
time.sleep(120)
'''

IGNORE_SIGTERM = r'''
import signal, sys, time, os
signal.signal(signal.SIGTERM, signal.SIG_IGN)
marker = os.environ.get("NX_MARKER")
if marker:
    with open(marker, "w") as fh:
        fh.write("term-ignored\n")
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(120)
    os._exit(0)
print("ignoring", flush=True)
time.sleep(120)
'''

DESCRIPTOR_REPORT = r'''
import json, os, sys, time
def extras():
    return [fd for fd in range(3, 256) if _check(fd)]
def _check(fd):
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False
print(json.dumps(dict(kind="leader", pid=os.getpid(), extras=extras())), flush=True)
child = os.fork()
if child == 0:
    print(json.dumps(dict(kind="grandchild", pid=os.getpid(), extras=extras())), flush=True)
    os._exit(0)
os.waitpid(child, 0)
line = sys.stdin.readline()
print(json.dumps(dict(kind="echo", message=line.strip())), flush=True)
sys.stderr.write("stderr-marker\n")
time.sleep(120)
'''

CHILDREN_64 = r'''
import os, time, json, sys
children = []
for _ in range(64):
    pid = os.fork()
    if pid == 0:
        time.sleep(120)
        os._exit(0)
    children.append(pid)
escaped = os.fork()
if escaped == 0:
    os.setsid()
    time.sleep(120)
    os._exit(0)
children.append(escaped)
print(json.dumps(dict(kind="spawned", count=len(children))), flush=True)
while True:
    time.sleep(0.2)
'''

PID_CHURN = r'''
import os, time, json
print(json.dumps(dict(kind="churner", pid=os.getpid())), flush=True)
deadline = time.time() + 60
while time.time() < deadline:
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
'''

SIGSTOP_TREE = r'''
import os, signal, time, json
print(json.dumps(dict(kind="stopper", pid=os.getpid())), flush=True)
for _ in range(3):
    pid = os.fork()
    if pid == 0:
        os.kill(os.getpid(), signal.SIGSTOP)
        time.sleep(120)
        os._exit(0)
time.sleep(120)
'''

NORMAL_EXIT = r'''
import os, time, json
child = os.fork()
if child == 0:
    time.sleep(120)
    os._exit(0)
print(json.dumps(dict(kind="exiting", pid=os.getpid(), child=child)), flush=True)
import sys
sys.exit(7)
'''


def load_backend():
    sys.path.insert(0, str(ROOT / 'src'))
    from nexus_connector_core.native.process import (
        observe_owned_process, owned_tree_census, spawn_owned_process)
    from nexus_connector_core.native.process.macos_abi import coalition_members
    from nexus_connector_core.native.process.macos_process import launchctl
    return dict(spawn_owned_process=spawn_owned_process,
                observe_owned_process=observe_owned_process,
                owned_tree_census=owned_tree_census,
                coalition_members=coalition_members, launchctl=launchctl)


def owned(backend, code, **kwargs):
    return backend['spawn_owned_process'](
        (sys.executable, '-I', '-c', code),
        cwd=kwargs.pop('cwd', '/tmp'), env=kwargs.pop('env', dict(os.environ)),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, **kwargs)


def close_streams(process):
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            with contextlib.suppress(OSError, ValueError):
                stream.close()


def survivors(backend, process):
    result = backend['coalition_members'](
        process._coalition_pair, exclude={process._guardian_pid})
    return [pid for pid, _birth in result.members], result.incomplete


def wait_census(backend, process, count, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        census = backend['owned_tree_census'](process)
        if census['count'] >= count:
            return census
        time.sleep(0.05)
    return backend['owned_tree_census'](process)


def label_registered(backend, label):
    query = backend['launchctl']('print', f'gui/{os.getuid()}/{label}')
    return query.returncode == 0


def fd_count():
    return len(os.listdir('/dev/fd'))


def scenario_double_fork(backend, runs):
    rows = dict(runs=0, proven=0, leaked=0, census_failures=0, label_leaks=0,
                timings=[])
    for index in range(runs):
        process = owned(backend, DOUBLE_FORK_ESCAPE)
        try:
            rows['runs'] += 1
            started = time.monotonic()
            census = wait_census(backend, process, 2)
            if census['count'] < 2:
                rows['census_failures'] += 1
                continue
            process.kill()
            process.wait(timeout=20)
            elapsed = time.monotonic() - started
            rows['timings'].append(round(elapsed, 4))
            if process.tree_stopped:
                rows['proven'] += 1
            left, incomplete = survivors(backend, process)
            if left or incomplete:
                rows['leaked'] += 1
            if label_registered(backend, process._label):
                rows['label_leaks'] += 1
        finally:
            with contextlib.suppress(Exception):
                process.kill()
                process.wait(timeout=20)
            close_streams(process)
    rows['max_seconds'] = max(rows['timings'], default=None)
    rows['avg_seconds'] = (round(sum(rows['timings']) / len(rows['timings']), 4)
                           if rows['timings'] else None)
    ok = (rows['proven'] == rows['runs'] and not rows['leaked']
          and not rows['census_failures'] and not rows['label_leaks'])
    return dict(status='PASS' if ok else 'FAIL', **rows)


def scenario_owner_sigkill(backend, runs=3):
    rows = dict(runs=0, drained=0, survivors=0)
    for _ in range(runs):
        with tempfile.TemporaryDirectory(prefix='nxacc-owner-') as directory:
            state = Path(directory) / 'state.json'
            observer = subprocess.Popen(
                [sys.executable, '-I', '-c', f'''
import json, os, sys, time
sys.path.insert(0, {str(ROOT / "src")!r})
from nexus_connector_core.native.process import spawn_owned_process
import subprocess
process = spawn_owned_process((sys.executable, "-I", "-c", {DOUBLE_FORK_ESCAPE!r}),
    cwd="/tmp", env=dict(os.environ), stdin=subprocess.PIPE,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
process.stdout.readline()
census = process.owned_tree_pids(64)
with open({str(state)!r}, "w") as fh:
    json.dump(dict(label=process._label, pair=list(process._coalition_pair),
                   guardian=process._guardian_pid, pids=census), fh)
time.sleep(60)
'''], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, close_fds=True)
            try:
                deadline = time.monotonic() + 10
                while not state.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not state.exists():
                    continue
                info = json.loads(state.read_text())
                rows['runs'] += 1
                observer.kill()
                observer.wait(timeout=5)
                # The guardian must drain the coalition after owner death.
                from nexus_connector_core.native.process.macos_abi import (
                    coalition_members)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = coalition_members(
                        tuple(info['pair']), exclude={info['guardian']})
                    if not result.members and not result.incomplete:
                        rows['drained'] += 1
                        break
                    time.sleep(0.1)
                else:
                    rows['survivors'] += 1
                with contextlib.suppress(Exception):
                    backend['launchctl']('bootout',
                                         f"gui/{os.getuid()}/{info['label']}")
            finally:
                if observer.poll() is None:
                    observer.kill()
                    observer.wait(timeout=5)
    return dict(status='PASS' if rows['runs'] == rows['drained'] else 'FAIL', **rows)


def scenario_cancel_escalation(backend):
    with tempfile.TemporaryDirectory(prefix='nxacc-term-') as directory:
        marker = str(Path(directory) / 'term.marker')
        env = dict(os.environ, NX_MARKER=marker)
        process = owned(backend, IGNORE_SIGTERM, env=env)
        try:
            process.stdout.readline()
            process.terminate()
            time.sleep(0.8)
            still_running = process.poll() is None
            process.kill()
            code = process.wait(timeout=20)
            term_delivered = Path(marker).exists()
            left, incomplete = survivors(backend, process)
            ok = (still_running and term_delivered and process.tree_stopped
                  and code == -9 and not left and not incomplete)
            return dict(status='PASS' if ok else 'FAIL',
                        ignored_sigterm=still_running, term_delivered=term_delivered,
                        exitcode=code, proven=process.tree_stopped,
                        survivors=len(left))
        finally:
            with contextlib.suppress(Exception):
                process.kill()
                process.wait(timeout=20)
            close_streams(process)


def scenario_descriptor_hygiene(backend):
    process = owned(backend, DESCRIPTOR_REPORT)
    try:
        process.stdin.write('roundtrip\n')
        process.stdin.flush()
        frames = [json.loads(process.stdout.readline()) for _ in range(3)]
        stderr_line = process.stderr.readline()
        kinds = {frame['kind']: frame for frame in frames}
        received_clean = all(
            not os.get_inheritable(fd)
            for fd in (process.stdin.fileno(), process.stdout.fileno(),
                       process.stderr.fileno()))
        hygiene = all(frame.get('extras') == []
                      for frame in kinds.values() if 'extras' in frame)
        roundtrip = kinds.get('echo', {}).get('message') == 'roundtrip'
        process.kill()
        process.wait(timeout=20)
        left, incomplete = survivors(backend, process)
        ok = (hygiene and roundtrip and received_clean and stderr_line.strip()
              and process.tree_stopped and not left and not incomplete)
        return dict(status='PASS' if ok else 'FAIL', hygiene=hygiene,
                    roundtrip=roundtrip, stderr=bool(stderr_line.strip()),
                    received_noninheritable=received_clean,
                    proven=process.tree_stopped, survivors=len(left))
    finally:
        with contextlib.suppress(Exception):
            process.kill()
            process.wait(timeout=20)
        close_streams(process)


def scenario_shared_coalition_refusal(backend):
    """Direct guardian run outside launchd: its coalition IS the caller's."""
    from nexus_connector_core.native.process.macos_abi import coalition_pair
    guardian = ROOT / 'src/nexus_connector_core/native/process/macos_process_guardian.py'
    with tempfile.TemporaryDirectory(prefix='nxacc-ref-', dir='/tmp') as directory:
        root = Path(directory)
        listener_path = root / 'control.sock'
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(listener_path))
        listener.listen(1)
        listener.settimeout(10)
        config = root / 'config.json'
        config.write_text(json.dumps(dict(
            socket=str(listener_path), token='refusal-token',
            owner_pid=os.getpid(), owner_birth=list(_own_birth()),
            caller_coalition=list(coalition_pair(os.getpid())),
            argv=[sys.executable, '-I', '-c',
                  'import sys; open(sys.argv[1], "w").write("spawned")',
                  str(root / 'spawned.marker')],
            cwd='/tmp', env=dict(os.environ))))
        probe = subprocess.run(
            [sys.executable, '-I', str(guardian), '--guardian', str(config)],
            capture_output=True, text=True, timeout=30, close_fds=True)
        try:
            connection, _ = listener.accept()
            connection.settimeout(5)
            data = connection.recv(4096)
            connection.close()
        except OSError:
            data = b''
        finally:
            listener.close()
        frame = json.loads(data.decode().strip()) if data.strip() else {}
        refused = (probe.returncode != 0
                   and frame.get('stage') == 'coalition_refusal'
                   and not (root / 'spawned.marker').exists())
        return dict(status='PASS' if refused else 'FAIL',
                    guardian_rc=probe.returncode,
                    refusal_stage=frame.get('stage'),
                    native_spawned=(root / 'spawned.marker').exists())


def _own_birth():
    from nexus_connector_core.native.process.macos_abi import identity
    return identity(os.getpid())['birth']


def scenario_census_overflow(backend):
    process = owned(backend, CHILDREN_64)
    try:
        process.stdout.readline()
        census = wait_census(backend, process, 65, timeout=15)
        bounded = process.owned_tree_pids(16)
        full = process.owned_tree_pids(256)
        overflow_ok = (bounded[1] is True and len(bounded[0]) == 16
                       and full[1] is False and len(full[0]) >= 65)
        count_ok = census['count'] >= 65
        process.kill()
        process.wait(timeout=30)
        left, incomplete = survivors(backend, process)
        ok = overflow_ok and count_ok and process.tree_stopped and not left
        return dict(status='PASS' if ok else 'FAIL', overflow=overflow_ok,
                    census_count=census['count'], bounded=len(bounded[0]),
                    full=len(full[0]), proven=process.tree_stopped,
                    survivors=len(left))
    finally:
        with contextlib.suppress(Exception):
            process.kill()
            process.wait(timeout=30)
        close_streams(process)


def scenario_slot_retention(backend):
    from nexus_connector_core.native.process.macos_process import OwnedDarwinPopen
    holders = []
    rows = dict(held=0, refused=False, released_then_accepted=False)
    try:
        for _ in range(32):
            holders.append(owned(backend, 'import time\nprint("up",flush=True)\ntime.sleep(120)'))
            holders[-1].stdout.readline()
        rows['held'] = len(holders)
        try:
            extra = owned(backend, 'import time\ntime.sleep(120)')
            close_streams(extra)
        except RuntimeError as exc:
            rows['refused'] = 'capacity exhausted' in str(exc)
        else:
            with contextlib.suppress(Exception):
                extra.kill()
                extra.wait(timeout=20)
        first = holders[0]
        first.kill()
        first.wait(timeout=20)
        rows['slot_released'] = first.tree_stopped
        close_streams(first)
        holders[0] = None
        try:
            replacement = owned(backend, 'import time\nprint("up",flush=True)\ntime.sleep(120)')
            replacement.stdout.readline()
            rows['released_then_accepted'] = True
        except RuntimeError:
            rows['released_then_accepted'] = False
        else:
            with contextlib.suppress(Exception):
                replacement.kill()
                replacement.wait(timeout=20)
            close_streams(replacement)
        ok = (rows['held'] == 32 and rows['refused']
              and rows['released_then_accepted'] and rows['slot_released'])
        return dict(status='PASS' if ok else 'FAIL', **rows)
    finally:
        for process in holders:
            if process is None:
                continue
            with contextlib.suppress(Exception):
                process.kill()
                process.wait(timeout=30)
            close_streams(process)
        OwnedDarwinPopen._slots = __import__('threading').BoundedSemaphore(32)


def scenario_pid_churn(backend):
    process = owned(backend, PID_CHURN)
    try:
        process.stdout.readline()
        time.sleep(0.3)
        process.kill()
        process.wait(timeout=30)
        left, incomplete = survivors(backend, process)
        ok = process.tree_stopped and not left and not incomplete
        return dict(status='PASS' if ok else 'FAIL', proven=process.tree_stopped,
                    survivors=len(left), incomplete=incomplete)
    finally:
        with contextlib.suppress(Exception):
            process.kill()
            process.wait(timeout=30)
        close_streams(process)


def scenario_sigstop_race(backend):
    process = owned(backend, SIGSTOP_TREE)
    try:
        process.stdout.readline()
        census = wait_census(backend, process, 4)
        process.kill()
        process.wait(timeout=30)
        left, incomplete = survivors(backend, process)
        ok = (census['count'] >= 4 and process.tree_stopped
              and not left and not incomplete)
        return dict(status='PASS' if ok else 'FAIL',
                    census_count=census['count'],
                    proven=process.tree_stopped, survivors=len(left))
    finally:
        with contextlib.suppress(Exception):
            process.kill()
            process.wait(timeout=30)
        close_streams(process)


def scenario_normal_exit(backend):
    process = owned(backend, NORMAL_EXIT)
    try:
        line = json.loads(process.stdout.readline())
        code = process.wait(timeout=20)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            left, incomplete = survivors(backend, process)
            if not left and not incomplete:
                break
            time.sleep(0.1)
        ok = (code == 7 and process.tree_stopped and not left
              and not incomplete)
        return dict(status='PASS' if ok else 'FAIL', exitcode=code,
                    grandchild=line.get('child'), proven=process.tree_stopped,
                    survivors=len(left))
    finally:
        with contextlib.suppress(Exception):
            process.kill()
            process.wait(timeout=20)
        close_streams(process)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=100,
                        help='double-fork/setsid escape iterations')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    report = dict(
        schema_version=1, platform=sys.platform, machine=platform.machine(),
        python=platform.python_version(), macos=platform.mac_ver()[0],
        script_sha256=hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        provider_execution=False, production_backend=True,
        scope=('single Intel host, GUI login domain, synthetic Python '
               'fixtures only; providers and integrated acceptance are '
               'separate campaigns'))
    if sys.platform != 'darwin':
        report.update(status='UNSUPPORTED_TEST_HOST')
    else:
        backend = load_backend()
        fds_before = fd_count()
        scenarios = {}
        started = time.monotonic()
        scenarios['double_fork_escape'] = scenario_double_fork(backend, args.runs)
        scenarios['owner_sigkill'] = scenario_owner_sigkill(backend)
        scenarios['cancel_escalation'] = scenario_cancel_escalation(backend)
        scenarios['descriptor_hygiene'] = scenario_descriptor_hygiene(backend)
        scenarios['shared_coalition_refusal'] = scenario_shared_coalition_refusal(backend)
        scenarios['census_overflow'] = scenario_census_overflow(backend)
        scenarios['slot_retention'] = scenario_slot_retention(backend)
        scenarios['pid_churn'] = scenario_pid_churn(backend)
        scenarios['sigstop_race'] = scenario_sigstop_race(backend)
        scenarios['normal_exit'] = scenario_normal_exit(backend)
        report['scenarios'] = scenarios
        report['fd_delta_after_campaign'] = fd_count() - fds_before
        report['elapsed_seconds'] = round(time.monotonic() - started, 1)
        report['status'] = ('PASS' if all(
            row['status'] == 'PASS' for row in scenarios.values())
            and report['fd_delta_after_campaign'] == 0 else 'FAIL')
    value = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(value, encoding='utf-8')
    print(value, end='')
    return 0 if report['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
