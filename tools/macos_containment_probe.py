"""Native feasibility evidence, not a containment backend or qualification.

Only --run-native creates a short-lived Python fixture. --scenarios adds bounded
synthetic Python fixtures that exercise the ownership questions a darwin backend
must answer (escaped descendants, owner death, descriptor inheritance, cancel,
census, launchd-job coalitions). No provider or shell is executed (launchctl is
used only to submit/remove the synthetic fixture); every fixture self-terminates with
SIGALRM and is only ever signalled after its (pid, birth) is re-verified.
Run with Python 3.11+ on the target Mac; no dependencies required.
ABI source: Apple XNU bsd/sys/proc_info.h (PROC_PIDTBSDINFO).
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import signal
import statistics
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
    # select.kqueue is not a context manager; closing() releases the descriptor.
    with contextlib.closing(select.kqueue()) as queue, tempfile.TemporaryDirectory(prefix='nexus-mac-probe-') as cwd:
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


# ---------------------------------------------------------------------------
# Scenarios (--scenarios)
# ---------------------------------------------------------------------------
SZOMB = 5
_LIB = None


def _libproc():
    global _LIB
    if _LIB is None:
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                     ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.proc_listallpids.restype = ctypes.c_int
        _LIB = lib
    return _LIB


def bsd(pid: int):
    """Non-raising process read; None when the PID is not observable."""
    info = BsdInfo()
    count = _libproc().proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if count != ctypes.sizeof(info) or info.pid != pid:
        return None
    return dict(pid=pid, ppid=info.ppid, pgid=info.pgid, status=info.status,
                birth=(info.start_sec, info.start_usec))


def snapshot() -> dict:
    lib = _libproc()
    count = lib.proc_listallpids(None, 0)
    buffer = (ctypes.c_int * (count + 128))()
    count = lib.proc_listallpids(buffer, ctypes.sizeof(buffer))
    result = {}
    for pid in buffer[:max(count, 0)]:
        if pid > 0:
            info = bsd(pid)
            if info is not None:
                result[pid] = info
    return result


def alive(pid: int, birth) -> bool:
    info = bsd(pid)
    return info is not None and info['birth'] == tuple(birth) and info['status'] != SZOMB


class Tracker:
    """Prototype tree tracker: kqueue EVFILT_PROC + libproc ppid scans.

    No NOTE_TRACK (documented unsupported). Members map pid -> birth; a PID is
    only ever signalled after its recorded birth is re-read.
    """

    def __init__(self, root_pid: int, poll: bool = False):
        self.kq = select.kqueue()
        self.members = {}
        self.exited = {}
        self.events = []
        self.errors = []
        self.first_seen = {}
        self.poll = poll
        self.scans = 0
        self.admit(root_pid, bsd(root_pid))

    def close(self):
        self.kq.close()

    def admit(self, pid, info):
        if info is None or pid in self.members:
            return
        self.members[pid] = info['birth']
        self.first_seen[pid] = time.time()
        fflags = select.KQ_NOTE_EXIT | select.KQ_NOTE_FORK | select.KQ_NOTE_EXEC
        try:
            self.kq.control([select.kevent(
                pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                fflags=fflags)], 0, 0)
        except OSError as exc:
            self.errors.append((pid, exc.errno))

    def scan(self):
        self.scans += 1
        snap = snapshot()
        changed = True
        while changed:
            changed = False
            for pid, info in snap.items():
                if pid in self.members or info['status'] == SZOMB:
                    continue
                parent = self.members.get(info['ppid'])
                if parent is not None and info['birth'] >= parent:
                    self.admit(pid, info)
                    changed = True

    def pump(self, timeout: float = 0.0):
        need_scan = self.poll
        try:
            events = self.kq.control(None, 32, timeout)
        except OSError:
            events = []
        for event in events:
            if event.flags & select.KQ_EV_ERROR:
                self.errors.append((event.ident, event.data))
                continue
            self.events.append((time.time(), event.ident, event.fflags))
            if event.fflags & select.KQ_NOTE_EXIT:
                self.exited.setdefault(event.ident, time.time())
            if event.fflags & (select.KQ_NOTE_FORK | select.KQ_NOTE_EXEC):
                need_scan = True
        if need_scan:
            self.scan()

    def live_members(self):
        return {pid: birth for pid, birth in self.members.items() if alive(pid, birth)}

    def kill_all(self, deadline: float = 5.0) -> dict:
        """SIGKILL every verified member until none is live; report timing/leaks."""
        start = time.monotonic()
        signalled = set()
        rounds = 0
        while time.monotonic() - start < deadline:
            rounds += 1
            self.scan()
            live = self.live_members()
            if not live:
                return dict(empty=True, rounds=rounds, signalled=len(signalled),
                            seconds=round(time.monotonic() - start, 4))
            for pid, birth in live.items():
                if alive(pid, birth):  # re-verify immediately before signalling
                    try:
                        os.kill(pid, signal.SIGKILL)
                        signalled.add(pid)
                    except ProcessLookupError:
                        pass
            self.pump(0.01)
        return dict(empty=False, rounds=rounds, signalled=len(signalled),
                    survivors=sorted(self.live_members()),
                    seconds=round(time.monotonic() - start, 4))


GUARDIAN = r'''import os, sys, json, time, signal, select, subprocess
signal.alarm(25)
log, owner, rfd, wfd, leak = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), sys.argv[6] == "1"
def emit(tag, **kw):
    kw.update(tag=tag, pid=os.getpid(), t=time.time())
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.write(fd, (json.dumps(kw) + "\n").encode()); os.close(fd)
kq = select.kqueue()
kq.control([select.kevent(rfd, filter=select.KQ_FILTER_READ, flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE),
            select.kevent(owner, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
                          fflags=select.KQ_NOTE_EXIT)], 0, 0)
native = subprocess.Popen([sys.executable, "-I", "-c", "import time, signal; signal.alarm(25); time.sleep(20)"],
                          pass_fds=((wfd,) if leak and wfd >= 0 else ()), close_fds=True, start_new_session=True,
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
emit("guardian_ready", native=native.pid, owner=owner)
start, first, seen = time.time(), None, set()
while True:
    now = time.time()
    if first is not None and now - first > 1.5:
        break
    if first is None and now - start > 8:
        emit("no_signal"); break
    for ev in kq.control(None, 8, 0.2):
        if ev.filter == select.KQ_FILTER_READ and "eof" not in seen:
            if os.read(rfd, 1) == b"":
                seen.add("eof"); emit("signal_pipe_eof"); first = first or time.time()
        elif ev.filter == select.KQ_FILTER_PROC and "kq" not in seen:
            seen.add("kq"); emit("signal_kqueue_owner_exit"); first = first or time.time()
    if os.getppid() == 1 and "ppid1" not in seen:
        seen.add("ppid1"); emit("signal_ppid_1"); first = first or time.time()
try:
    os.killpg(native.pid, signal.SIGKILL)
except ProcessLookupError:
    pass
emit("killpg_issued")
native.wait(); emit("cleaned")
'''

SCEN = r'''import os, sys, json, time, signal, select, subprocess
signal.alarm(25)
role, log = sys.argv[1], sys.argv[2]
def emit(tag, **kw):
    kw.update(tag=tag, pid=os.getpid(), ppid=os.getppid(), pgid=os.getpgrp(), t=time.time())
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.write(fd, (json.dumps(kw) + "\n").encode()); os.close(fd)
def wait_go():
    if not select.select([0], [], [], 10)[0]:
        os._exit(2)
    os.read(0, 1)
def open_fds():
    found = []
    for fd in range(3, 256):
        try:
            os.fstat(fd); found.append(fd)
        except OSError:
            pass
    return found
try:
    if role == "leader_setsid":
        emit("leader"); wait_go()
        if os.fork() == 0:
            os.setsid(); emit("escaped"); time.sleep(20); os._exit(0)
        time.sleep(20)
    elif role == "leader_double":
        delay, use_setsid = float(sys.argv[3]), sys.argv[4] == "1"
        emit("leader"); wait_go()
        mid = os.fork()
        if mid == 0:
            if use_setsid:
                os.setsid()
            if os.fork() == 0:
                emit("B"); time.sleep(20); os._exit(0)
            time.sleep(delay); emit("A_exit"); os._exit(0)
        os.waitpid(mid, 0)
        time.sleep(20)
    elif role == "ignore_term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        emit("leader"); wait_go(); emit("running"); time.sleep(20)
    elif role == "term_default":
        emit("leader"); wait_go(); emit("running"); time.sleep(20)
    elif role == "many":
        count = int(sys.argv[3])
        emit("leader"); wait_go()
        for _ in range(count):
            if os.fork() == 0:
                time.sleep(20); os._exit(0)
        emit("spawned", count=count); time.sleep(20)
    elif role == "fdreport":
        emit("leader"); wait_go()
        child = os.fork()
        if child == 0:
            emit("fds_grandchild", fds=open_fds()); os._exit(0)
        os.waitpid(child, 0)
        emit("fds_leader", fds=open_fds())
    elif role == "owner":
        leak = sys.argv[3] == "1"
        r, w = os.pipe()
        g = subprocess.Popen([sys.executable, "-I", "-c", sys.argv[4], "guardian", log,
                              str(os.getpid()), str(r), str(w), "1" if leak else "0"],
                             pass_fds=((r, w) if leak else (r,)), close_fds=True, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        emit("owner_ready", guardian=g.pid); time.sleep(20)
except BaseException as exc:
    emit("error", error=type(exc).__name__ + ": " + str(exc)); os._exit(9)
'''


class Fixtures:
    """Owns every spawned fixture so cleanup is verified and total."""

    def __init__(self, root: str):
        self.root = root
        self.seq = 0
        self.procs = []
        self.learned = {}

    def log_path(self) -> str:
        self.seq += 1
        return os.path.join(self.root, f'log{self.seq}.jsonl')

    def launch(self, role, log, *args, extra=()):
        proc = subprocess.Popen(
            [sys.executable, '-I', '-c', SCEN, role, log, *map(str, args), *extra],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=self.root, env={}, close_fds=True, start_new_session=True)
        self.procs.append(proc)
        return proc

    def learn(self, pid):
        info = bsd(pid)
        if info is not None:
            self.learned.setdefault(pid, info['birth'])
        return info

    def final_cleanup(self) -> dict:
        killed = []
        for pid, birth in self.learned.items():
            if alive(pid, birth):
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed.append(pid)
                except ProcessLookupError:
                    pass
        for proc in self.procs:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            if proc.stdin:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
        time.sleep(0.2)
        left = [pid for pid, birth in self.learned.items() if alive(pid, birth)]
        return dict(force_killed_after_scenarios=sorted(killed), still_alive=left)


def read_log(path):
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def wait_tag(path, tag, timeout=4.0, count=1, pump=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hits = [e for e in read_log(path) if e['tag'] == tag]
        if len(hits) >= count:
            return hits
        if pump:
            pump()
        else:
            time.sleep(0.005)
    return [e for e in read_log(path) if e['tag'] == tag]


def release(proc):
    proc.stdin.write(b'G')
    proc.stdin.flush()


def scenario_setsid_escape(fx):
    """A descendant that calls setsid() leaves the leader's process group."""
    log = fx.log_path()
    leader = fx.launch('leader_setsid', log)
    tracker = Tracker(leader.pid)
    try:
        wait_tag(log, 'leader')
        t_go = time.time()
        release(leader)
        hits = wait_tag(log, 'escaped', pump=lambda: tracker.pump(0.002))
        if not hits:
            return dict(status='ERROR', error='escaped descendant never reported', log=read_log(log))
        esc = hits[0]
        tracker.pump(0.05)
        info = fx.learn(esc['pid'])
        out = dict(status='OBSERVED', escaped_pid_left_group=esc['pgid'] != leader.pid,
                   escaped_pgid_equals_own_pid=esc['pgid'] == esc['pid'],
                   tracker_admitted_escaped=esc['pid'] in tracker.members,
                   tracker_admit_latency_ms=(round((tracker.first_seen[esc['pid']] - esc['t']) * 1000, 2)
                                             if esc['pid'] in tracker.first_seen else None),
                   tracker_errors=tracker.errors, scans=tracker.scans)
        os.killpg(leader.pid, signal.SIGKILL)
        leader.wait(timeout=3)
        time.sleep(0.3)
        after = bsd(esc['pid'])
        out['survives_killpg_of_leader_group'] = bool(info and alive(esc['pid'], info['birth']))
        out['escaped_reparented_to_pid'] = after['ppid'] if after else None
        before_events = len(tracker.events)
        out['tracker_kill'] = tracker.kill_all()
        tracker.pump(0.2)
        out['kqueue_exit_event_for_non_child'] = any(
            ident == esc['pid'] and fflags & select.KQ_NOTE_EXIT
            for _t, ident, fflags in tracker.events[before_events:] + tracker.events[:before_events])
        out['escaped_dead_after_tracker_kill'] = not (info and alive(esc['pid'], info['birth']))
        return out
    finally:
        tracker.close()


def scenario_orphan_race(fx, iterations=12):
    """Double fork where the intermediate exits at once: can a tracker keep up?"""
    results = {}
    wall = time.monotonic()
    for use_setsid in (0, 1):
        for delay in (0.0, 0.02):
            for mode in ('event', 'poll'):
                key = f'setsid={use_setsid},mid_exit_delay={delay},tracker={mode}'
                row = dict(runs=0, tracked=0, survived_killpg=0, leaked_after_full_kill=0,
                           missing_report=0)
                for _ in range(iterations):
                    if time.monotonic() - wall > 150:
                        row['skipped_for_time_budget'] = True
                        break
                    log = fx.log_path()
                    leader = fx.launch('leader_double', log, delay, use_setsid)
                    tracker = Tracker(leader.pid, poll=(mode == 'poll'))
                    try:
                        wait_tag(log, 'leader')
                        release(leader)
                        b = wait_tag(log, 'B', pump=lambda: tracker.pump(0.002))
                        wait_tag(log, 'A_exit', timeout=2, pump=lambda: tracker.pump(0.002))
                        row['runs'] += 1
                        if not b:
                            row['missing_report'] += 1
                            continue
                        tracker.pump(0.02)
                        b_pid = b[0]['pid']
                        info = fx.learn(b_pid)
                        if b_pid in tracker.members:
                            row['tracked'] += 1
                        os.killpg(leader.pid, signal.SIGKILL)
                        leader.wait(timeout=3)
                        time.sleep(0.05)
                        if info and alive(b_pid, info['birth']):
                            row['survived_killpg'] += 1
                        tracker.kill_all(deadline=1.0)
                        if info and alive(b_pid, info['birth']):
                            row['leaked_after_full_kill'] += 1
                    finally:
                        tracker.close()
                results[key] = row
    return dict(status='OBSERVED', combos=results,
                total_runs=sum(r['runs'] for r in results.values()),
                total_leaks=sum(r['leaked_after_full_kill'] for r in results.values()))


def scenario_owner_death(fx):
    """Which owner-death signal reaches an orphaned guardian, and how fast?"""
    out = dict(status='OBSERVED')
    for label, leak in (('correct_fd_hygiene', 0), ('negative_control_native_inherits_pipe_end', 1)):
        log = fx.log_path()
        owner = fx.launch('owner', log, leak, extra=(GUARDIAN,))
        ready = wait_tag(log, 'guardian_ready', timeout=5)
        if not ready:
            out[label] = dict(status='ERROR', log=read_log(log))
            continue
        fx.learn(ready[0]['pid'])
        fx.learn(ready[0]['native'])
        t0 = time.time()
        os.kill(owner.pid, signal.SIGKILL)
        owner.wait(timeout=3)
        cleaned = wait_tag(log, 'cleaned', timeout=6)
        events = {e['tag']: round((e['t'] - t0) * 1000, 1) for e in read_log(log)
                  if e['tag'].startswith('signal_') or e['tag'] in ('killpg_issued', 'cleaned', 'no_signal')}
        native_pid = ready[0]['native']
        out[label] = dict(
            latency_ms_after_owner_sigkill=events,
            pipe_eof_delivered='signal_pipe_eof' in events,
            kqueue_owner_exit_delivered='signal_kqueue_owner_exit' in events,
            guardian_saw_ppid_1='signal_ppid_1' in events,
            guardian_cleaned_native=bool(cleaned),
            native_dead=not alive(native_pid, fx.learned.get(native_pid, (0, 0))))
    return out


def scenario_fd_inheritance(fx):
    """Descriptors visible to a native child and grandchild after close_fds=True."""
    extra = [os.pipe() for _ in range(3)]
    log = fx.log_path()
    try:
        leader = fx.launch('fdreport', log)
        wait_tag(log, 'leader')
        release(leader)
        got = wait_tag(log, 'fds_leader', timeout=4)
        grand = [e for e in read_log(log) if e['tag'] == 'fds_grandchild']
        return dict(status='OBSERVED',
                    parent_open_extra_descriptors=len(extra) * 2,
                    leader_inherited_fds=got[0]['fds'] if got else None,
                    grandchild_inherited_fds=grand[0]['fds'] if grand else None,
                    clean=bool(got) and not got[0]['fds'])
    finally:
        for r, w in extra:
            os.close(r)
            os.close(w)


def scenario_cancel(fx):
    """SIGTERM-ignoring leader: graceful request then forceful kill."""
    out = dict(status='OBSERVED')
    log = fx.log_path()
    leader = fx.launch('ignore_term', log)
    tracker = Tracker(leader.pid)
    try:
        wait_tag(log, 'leader')
        release(leader)
        wait_tag(log, 'running')
        os.killpg(leader.pid, signal.SIGTERM)
        time.sleep(0.5)
        out['sigterm_ignored_leader_still_alive'] = leader.poll() is None
        t0 = time.monotonic()
        os.killpg(leader.pid, signal.SIGKILL)
        leader.wait(timeout=3)
        out['sigkill_stop_seconds'] = round(time.monotonic() - t0, 4)
        out['kill_all'] = tracker.kill_all()
    finally:
        tracker.close()
    log = fx.log_path()
    leader = fx.launch('term_default', log)
    try:
        wait_tag(log, 'leader')
        release(leader)
        wait_tag(log, 'running')
        t0 = time.monotonic()
        os.killpg(leader.pid, signal.SIGTERM)
        leader.wait(timeout=3)
        out['default_sigterm_stop_seconds'] = round(time.monotonic() - t0, 4)
        out['default_sigterm_returncode'] = leader.returncode
    finally:
        pass
    return out


def scenario_census(fx, count=64, limit=16):
    """Bounded census and scan cost for a wide tree."""
    log = fx.log_path()
    leader = fx.launch('many', log, count)
    tracker = Tracker(leader.pid)
    try:
        wait_tag(log, 'leader')
        release(leader)
        wait_tag(log, 'spawned', timeout=6)
        tracker.pump(0.1)
        tracker.scan()
        costs = []
        for _ in range(5):
            t0 = time.perf_counter()
            snap = snapshot()
            costs.append((time.perf_counter() - t0) * 1000)
        tree = [pid for pid, info in snap.items() if info['pgid'] == leader.pid]
        out = dict(status='OBSERVED', requested_children=count,
                   tracker_members=len(tracker.members),
                   tracker_matches_expected=len(tracker.members) == count + 1,
                   process_group_census=len(tree),
                   census_limit=limit,
                   overflow_reported=len(tree) > limit,
                   host_process_count=len(snap),
                   full_scan_ms_median=round(statistics.median(costs), 2),
                   full_scan_ms_max=round(max(costs), 2))
        os.killpg(leader.pid, signal.SIGKILL)
        leader.wait(timeout=3)
        out['kill_all'] = tracker.kill_all()
        return out
    finally:
        tracker.close()


def scenario_pid_space(fx):
    """PID allocation pattern and the cost of the verify-then-signal window."""
    pids = []
    for _ in range(80):
        proc = subprocess.Popen(['/usr/bin/true'], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        pids.append(proc.pid)
        proc.wait()
    deltas = [b - a for a, b in zip(pids, pids[1:])]
    t0 = time.perf_counter()
    window = []
    me = os.getpid()
    for _ in range(2000):
        a = time.perf_counter()
        info = bsd(me)
        os.kill(me, 0)
        window.append((time.perf_counter() - a) * 1e6)
    start = time.monotonic()
    probe = []
    for _ in range(40):
        proc = subprocess.Popen(['/usr/bin/true'], close_fds=True)
        probe.append(proc.pid)
        proc.wait()
    rate = len(probe) / max(time.monotonic() - start, 1e-9)
    return dict(status='OBSERVED', spawned=len(pids),
                monotonic_increasing=all(d > 0 for d in deltas),
                wrapped=any(d < 0 for d in deltas),
                delta_min=min(deltas), delta_median=statistics.median(deltas), delta_max=max(deltas),
                verify_then_signal_window_us_median=round(statistics.median(window), 1),
                verify_then_signal_window_us_p99=round(sorted(window)[int(len(window) * .99)], 1),
                spawn_rate_per_second=round(rate, 1),
                seconds_to_wrap_pid_space_at_that_rate=round(99999 / rate, 0))


def coalition_of(pid: int):
    """(resource, jetsam) coalition ids via proc_pidinfo(PROC_PIDCOALITIONINFO=20)."""
    buffer = (ctypes.c_uint64 * 8)()
    count = _libproc().proc_pidinfo(pid, 20, 0, buffer, ctypes.sizeof(buffer))
    return tuple(buffer[:2]) if count > 0 else None


def coalition_members(coalition, snap=None) -> dict:
    snap = snap if snap is not None else snapshot()
    return {pid: info['birth'] for pid, info in snap.items()
            if info['status'] != SZOMB and coalition_of(pid) == coalition}


def launchctl(*args):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True)


def scenario_coalition(fx, iterations=10):
    """Does a per-runtime launchd job give a membership key that survives the
    setsid + fast-exit double fork that no user-space tracker caught above?"""
    own = coalition_of(os.getpid())
    daemon_parent = coalition_of(1)
    rows = dict(runs=0, coalition_differs_from_caller=0, escaped_in_job_coalition=0,
                escaped_reparented_to_launchd=0, survives_launchctl_remove=0,
                found_by_coalition_census=0, leaked_after_coalition_kill=0,
                job_never_started=0)
    census_ms, kill_ms = [], []
    for index in range(iterations):
        label = f'ai.oktolabs.nexus-probe.{os.getpid()}.{index}'
        log = fx.log_path()
        try:
            submit = launchctl('submit', '-l', label, '-o', '/dev/null', '-e', '/dev/null', '--',
                               sys.executable, '-I', '-c', SCEN, 'leader_double', log, '0', '1')
            if submit.returncode != 0:
                return dict(status='ERROR', error='launchctl submit failed', stderr=submit.stderr.strip())
            leader = wait_tag(log, 'leader', timeout=5)
            b = wait_tag(log, 'B', timeout=5)
            wait_tag(log, 'A_exit', timeout=2)
            if not leader or not b:
                rows['job_never_started'] += 1
                continue
            rows['runs'] += 1
            leader_pid, b_pid = leader[0]['pid'], b[0]['pid']
            fx.learn(leader_pid)
            info = fx.learn(b_pid)
            job = coalition_of(leader_pid)
            rows['coalition_differs_from_caller'] += job is not None and job != own
            rows['escaped_in_job_coalition'] += coalition_of(b_pid) == job
            now = bsd(b_pid)
            rows['escaped_reparented_to_launchd'] += bool(now and now['ppid'] == 1)
            launchctl('remove', label)
            time.sleep(0.4)
            rows['survives_launchctl_remove'] += bool(info and alive(b_pid, info['birth']))
            if job is None or job in (own, daemon_parent):
                continue  # never signal a coalition shared with the caller or launchd
            t0 = time.perf_counter()
            members = coalition_members(job)
            census_ms.append((time.perf_counter() - t0) * 1000)
            rows['found_by_coalition_census'] += b_pid in members
            t0 = time.perf_counter()
            for _ in range(20):
                members = coalition_members(job)
                if not members:
                    break
                for pid, birth in members.items():
                    if alive(pid, birth) and coalition_of(pid) == job:  # re-verify, then signal
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                time.sleep(0.01)
            kill_ms.append((time.perf_counter() - t0) * 1000)
            rows['leaked_after_coalition_kill'] += bool(info and alive(b_pid, info['birth']))
        finally:
            launchctl('remove', label)
    leftovers = [label for label in launchctl('list').stdout.split()
                 if label.startswith(f'ai.oktolabs.nexus-probe.{os.getpid()}.')]
    return dict(status='OBSERVED', iterations=iterations, **rows,
                caller_coalition=own, launchd_labels_left_registered=leftovers,
                coalition_census_ms_median=round(statistics.median(census_ms), 2) if census_ms else None,
                coalition_kill_ms_median=round(statistics.median(kill_ms), 2) if kill_ms else None,
                same_scenario_without_coalitions='see orphan_race setsid=1,mid_exit_delay=0.0')


def run_scenarios() -> dict:
    report = {}
    with tempfile.TemporaryDirectory(prefix='nexus-mac-scen-') as root:
        fx = Fixtures(root)
        started = time.monotonic()
        try:
            for name, fn in (('setsid_escape', scenario_setsid_escape),
                             ('orphan_race', scenario_orphan_race),
                             ('owner_death', scenario_owner_death),
                             ('fd_inheritance', scenario_fd_inheritance),
                             ('cancel', scenario_cancel),
                             ('census', scenario_census),
                             ('pid_space', scenario_pid_space),
                             ('coalition', scenario_coalition)):
                try:
                    report[name] = fn(fx)
                except Exception as exc:  # one failing scenario must not hide the rest
                    report[name] = dict(status='ERROR', error=f'{type(exc).__name__}: {exc}')
        finally:
            report['cleanup'] = fx.final_cleanup()
            report['wall_seconds'] = round(time.monotonic() - started, 1)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-native', action='store_true', required=True,
                        help='Explicitly run the bounded synthetic Python fixture')
    parser.add_argument('--scenarios', action='store_true',
                        help='Also run the bounded ownership scenarios (adds ~30-60 s; runs launchctl submit/remove for per-job labels)')
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
            if args.scenarios:
                report.update(scenarios=run_scenarios(), status='SCENARIOS_OBSERVED')
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
