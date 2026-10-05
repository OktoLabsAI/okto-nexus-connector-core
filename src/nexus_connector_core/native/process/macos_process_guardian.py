"""launchd coalition guardian for owned Darwin processes.

This program is executed only by ``launchd`` from the generated per-session
job plist (``RunAtLoad=true``, ``KeepAlive=false``); it is never a payload
command and never runs provider code itself. The observer
(:mod:`nexus_connector_core.native.process.macos_process`) bootstraps the
job, keeps the control connection and removes the label.

Ownership contract implemented here, per
``plans/MACOS_INTEL_IMPLEMENTATION.md``:

- The tree key is the launchd job's coalition *pair*: a process belongs to
  the owned tree iff both its resource and jetsam coalition ids equal the
  guardian's. Coalition membership is inherited through ``fork`` and
  survives ``exec``, ``setsid`` and double-fork escapes (native evidence:
  10/10 escaped orphans found; zero alive after the kill pass).
- The guardian refuses to start a provider when its own pair shares either
  coalition type with the caller or with PID 1 — a shared coalition is not
  a usable ownership key.
- Signalling authority requires, per PID: census membership, birth
  revalidation, coalition revalidation, a ``SIGSTOP`` interlock (a stopped
  process cannot fork, exec or exit by itself) and a post-signal birth
  re-read that detects a recycled target instead of fabricating success.
- Stop proof ("D") requires two consecutive *complete* censuses with zero
  live non-zombie members. Incomplete scans, permission failures and
  enumeration overflow never count as an empty tree. ``launchctl bootout``
  is registration cleanup, never stop evidence.
- Owner death is detected through a kqueue ``NOTE_EXIT`` registration that
  brackets owner birth verification before the native launch; an inherited
  pipe writer never delays this signal.
- The guardian ignores SIGTERM/SIGINT: external removal cannot be allowed
  to interrupt or masquerade as cleanup. An unkillable member keeps the
  guardian alive rather than fabricating a proof after a deadline.

The guardian sends newline-delimited JSON frames over the AF_UNIX control
connection (token-checked). The stdin/stdout/stderr pipes of the native
process are handed to the observer with ``SCM_RIGHTS``; the guardian closes
its own copies so only the native tree owns the protocol pipes.
"""

from __future__ import annotations

import array
import contextlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time

STARTUP_ALARM_SECONDS = 75
CONNECT_TIMEOUT = 5.0
STOP_WAIT_SECONDS = 0.5
EMPTY_INTERVAL = 0.05
EMPTY_CENSUSES_REQUIRED = 2
TERMINATE_GRACE_SECONDS = 2.0
MONITOR_TICK = 0.05

GUARDIAN_EXITED_UNKNOWN = 125
GUARDIAN_FAILED = 126


def load_abi():
    """Import the installed Core ABI under ``python -I`` isolation."""
    from nexus_connector_core.native.process import macos_abi

    return macos_abi


def coalition_conflict(own, caller, launchd) -> bool:
    """True when any coalition type is shared with the caller or PID 1.

    Refusing a single shared type is deliberate: a key that matches the
    caller's or launchd's resource or jetsam coalition cannot separate the
    owned tree from processes the guardian must never signal.
    """
    return any(own[index] in (caller[index], launchd[index])
               for index in (0, 1))


def send_frame(connection, frame, descriptors=()):
    payload = json.dumps(frame).encode() + b'\n'
    if descriptors:
        fds = array.array('i', descriptors)
        sent = connection.sendmsg([payload],
                                  [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds)])
    else:
        sent = connection.send(payload)
    if sent != len(payload):
        raise OSError('incomplete control frame')


def _safe_identity(abi, pid):
    try:
        return abi.identity(pid)
    except ProcessLookupError:
        return None


def census(abi, own_pair, exclude, seen=None, confirmed=None):
    """Coalition census; ``None`` marks an unreadable (never empty) pass."""
    try:
        return abi.coalition_members(own_pair, exclude=exclude, seen=seen,
                                     confirmed_dead=confirmed)
    except OSError:
        return None


class ExitWatchers:
    """kqueue ``NOTE_EXIT`` watchers for every censused member.

    A watcher is bound to the kernel process object, so PID recycling
    cannot forge or mask it. A fired watcher confirms that exact
    member's death; only then may a later unreadable reuse of its PID be
    classified as a recycled foreign process instead of an unproven
    (possibly setuid-transitioned) member. Registration is best effort:
    failures simply leave the conservative path in place.
    """

    def __init__(self):
        self.queue = select.kqueue()
        self.confirmed = set()
        self.pending = set()

    def close(self):
        self.queue.close()

    def register(self, pid):
        if pid in self.pending or pid in self.confirmed:
            return
        try:
            self.queue.control([select.kevent(
                pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                fflags=select.KQ_NOTE_EXIT)], 0, 0)
            self.pending.add(pid)
        except OSError:
            pass

    def pump(self):
        try:
            events = self.queue.control(None, 256, 0)
        except OSError:
            return
        for event in events:
            if event.fflags & select.KQ_NOTE_EXIT:
                self.confirmed.add(event.ident)
                self.pending.discard(event.ident)


def stop_member(abi, pid, birth, own_pair) -> str:
    """Stop-and-kill one verified member.

    Outcomes: ``killed`` (SIGKILL delivered to the birth-verified process,
    post-signal identity confirmed), ``gone`` (disappeared), ``skipped``
    (identity/coalition changed — re-evaluated by the next census) or
    ``suspect`` (post-signal birth differs: a recycled PID may have been
    signalled; the caller must refuse the stop proof).
    """
    ident = _safe_identity(abi, pid)
    if ident is None or tuple(ident['birth']) != birth:
        return 'gone' if ident is None else 'skipped'
    try:
        if abi.coalition_pair(pid) != own_pair:
            return 'skipped'
    except ProcessLookupError:
        return 'gone'
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGSTOP)
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while True:
        ident = _safe_identity(abi, pid)
        if ident is None:
            return 'gone'
        if tuple(ident['birth']) != birth:
            return 'skipped'
        if ident['status'] == abi.SSTOP:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.005)
    # A stopped process cannot fork, exec or exit on its own, so this
    # re-read runs against a stable target. It still does not eliminate
    # the microsecond race to the signal itself; the post-signal re-read
    # below detects a recycled victim instead of assuming the kill.
    ident = _safe_identity(abi, pid)
    if ident is None:
        return 'gone'
    if tuple(ident['birth']) != birth:
        return 'skipped'
    try:
        if abi.coalition_pair(pid) != own_pair:
            return 'skipped'
    except ProcessLookupError:
        return 'gone'
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return 'gone'
    after = _safe_identity(abi, pid)
    if after is None:
        return 'killed'
    return 'killed' if tuple(after['birth']) == birth else 'suspect'


def force_drain(abi, own_pair, exclude, stats, seen, watchers=None) -> bool:
    """Bounded-per-pass, unbounded-in-time coalition drain.

    Each pass stops and kills every verified live member. The proof needs
    ``EMPTY_CENSUSES_REQUIRED`` consecutive complete empty censuses; an
    incomplete or non-empty pass resets the count. There is deliberately
    no overall deadline: an unkillable member keeps the guardian alive
    holding ownership rather than reporting a stop it cannot prove.
    """
    empties = 0
    while True:
        stats['rounds'] += 1
        if watchers is not None:
            watchers.pump()
        result = census(abi, own_pair, exclude, seen,
                        watchers.confirmed if watchers is not None else None)
        if result is None or result.incomplete:
            stats['incomplete_passes'] += 1
            empties = 0
            time.sleep(EMPTY_INTERVAL)
            continue
        stats['foreign_denied'] = result.foreign_denied
        stats['recycled_after_death'] = result.recycled_after_death
        if not result.members:
            empties += 1
            if empties >= EMPTY_CENSUSES_REQUIRED:
                return True
            time.sleep(EMPTY_INTERVAL)
            continue
        empties = 0
        for pid, birth in result.members:
            if watchers is not None:
                watchers.register(pid)
            outcome = stop_member(abi, pid, birth, own_pair)
            stats[outcome] = stats.get(outcome, 0) + 1
            if outcome == 'killed' and watchers is not None:
                watchers.confirmed.add(pid)
                watchers.pending.discard(pid)
        time.sleep(0.01)


def terminate_pass(abi, own_pair, exclude, leader, connection, stats, seen,
                   watchers=None):
    """SIGTERM pass, then a bounded grace before the observer escalates."""
    result = census(abi, own_pair, exclude, seen,
                    watchers.confirmed if watchers is not None else None)
    members = result.members if result is not None else []
    for pid, birth in members:
        ident = _safe_identity(abi, pid)
        if ident is None or tuple(ident['birth']) != birth:
            continue
        try:
            if abi.coalition_pair(pid) != own_pair:
                continue
        except ProcessLookupError:
            continue
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        stats['termed'] = stats.get('termed', 0) + 1
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    empties = 0
    while time.monotonic() < deadline:
        if leader.poll() is not None:
            break
        try:
            readable, _, _ = select.select([connection], [], [], 0)
        except OSError:
            return
        if readable:
            try:
                if not connection.recv(1):
                    return  # observer closed the channel: force escalation
            except OSError:
                return
        result = census(abi, own_pair, exclude, seen,
                        watchers.confirmed if watchers is not None else None)
        if result is None or not result.empty:
            empties = 0
            continue
        empties += 1
        if empties >= EMPTY_CENSUSES_REQUIRED and leader.poll() is not None:
            return
        time.sleep(MONITOR_TICK)


def run(config_path: str) -> int:
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    # The config carries the sealed native environment; drop it once loaded.
    with contextlib.suppress(OSError):
        os.unlink(config_path)
    signal.alarm(STARTUP_ALARM_SECONDS)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    abi = load_abi()
    token = config['token']
    own_pair = abi.coalition_pair(os.getpid())
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(CONNECT_TIMEOUT)
    watcher = select.kqueue()
    native = None
    native_birth = None
    seen = {}
    watchers = ExitWatchers()
    stats = dict(rounds=0, incomplete_passes=0, killed=0, gone=0,
                 skipped=0, suspect=0, termed=0, foreign_denied=0,
                 recycled_after_death=0)
    try:
        connection.connect(config['socket'])
        connection.settimeout(None)
        caller_pair = tuple(config['caller_coalition'])
        launchd_pair = abi.coalition_pair(1)
        if coalition_conflict(own_pair, caller_pair, launchd_pair):
            send_frame(connection, dict(
                kind='error', token=token, stage='coalition_refusal',
                error='RuntimeError',
                detail='guardian coalition shares a type with caller or launchd'))
            return GUARDIAN_FAILED
        owner_pid = config['owner_pid']
        owner_birth = tuple(config['owner_birth'])
        if tuple(abi.identity(owner_pid)['birth']) != owner_birth:
            send_frame(connection, dict(
                kind='error', token=token, stage='owner_birth',
                error='RuntimeError', detail='owner birth changed before watch'))
            return GUARDIAN_FAILED
        watcher.control([select.kevent(
            owner_pid, filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_EXIT)], 0, 0)
        # Bracket the registration with birth re-reads: a dead owner must be
        # caught here, not masked by an inherited pipe writer keeping EOF away.
        if (tuple(abi.identity(owner_pid)['birth']) != owner_birth
                or watcher.control(None, 1, 0)):
            send_frame(connection, dict(
                kind='error', token=token, stage='owner_exit_early',
                error='RuntimeError', detail='owner exited before native launch'))
            return GUARDIAN_FAILED
        try:
            # SIG_IGN survives fork+exec: the native tree must receive the
            # default dispositions the observer's own Popen would give it,
            # otherwise graceful terminate() could never be delivered. The
            # guardian re-ignores both signals immediately after the spawn.
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            native = subprocess.Popen(
                config['argv'], cwd=config['cwd'], env=config['env'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
        except OSError as exc:
            send_frame(connection, dict(
                kind='error', token=token, stage='native_spawn',
                error=type(exc).__name__, errno=exc.errno,
                strerror=exc.strerror, filename=exc.filename))
            return GUARDIAN_FAILED
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        native_birth = tuple(abi.identity(native.pid)['birth'])
        if abi.coalition_pair(native.pid) != own_pair:
            raise RuntimeError('native process did not inherit the job coalition')
        watchers.register(native.pid)
        send_frame(connection, dict(
            kind='handoff', token=token, pid=native.pid,
            birth=list(native_birth), guardian_pid=os.getpid()),
            descriptors=[native.stdin.fileno(), native.stdout.fileno(),
                         native.stderr.fileno()])
        # Only the native tree owns the protocol pipes from here.
        for stream in (native.stdin, native.stdout, native.stderr):
            stream.close()
        signal.alarm(0)  # steady state: cleanup is intentionally unbounded

        mode = None
        while mode is None:
            if native.poll() is not None:
                mode = 'native_exit'
                break
            if watcher.control(None, 1, 0):
                mode = 'owner_exit'
                break
            try:
                readable, _, _ = select.select([connection], [], [], MONITOR_TICK)
            except OSError:
                mode = 'observer_gone'
                break
            if not readable:
                continue
            try:
                request = connection.recv(64)
            except OSError:
                mode = 'observer_gone'
                break
            if not request:
                mode = 'observer_gone'
            elif b'T' in request:
                mode = 'terminate'
            else:
                continue

        stats['mode'] = mode
        if mode == 'terminate':
            terminate_pass(abi, own_pair, {os.getpid()}, native, connection,
                           stats, seen, watchers)
        proven = force_drain(abi, own_pair, {os.getpid()}, stats, seen,
                             watchers)
        if native.poll() is None:
            with contextlib.suppress(OSError):
                os.kill(native.pid, signal.SIGKILL)
        exitcode = native.wait()
        proof = 'D' if proven and not stats.get('suspect') else 'E'
        send_frame(connection, dict(
            kind='final', token=token, proof=proof, mode=mode,
            exitcode=exitcode, stats=stats))
        return 0 if proof == 'D' else GUARDIAN_EXITED_UNKNOWN
    except BaseException as exc:  # noqa: BLE001 - reported to the observer
        # Any failure after the native launch still owns the tree: drain it
        # before reporting, never leak it into the job coalition.
        if native is not None:
            with contextlib.suppress(Exception):
                force_drain(abi, own_pair, {os.getpid()}, stats, seen, watchers)
            with contextlib.suppress(Exception):
                if native.poll() is None:
                    os.kill(native.pid, signal.SIGKILL)
                native.wait()
        with contextlib.suppress(OSError):
            send_frame(connection, dict(
                kind='error', token=token, stage='guardian',
                error=type(exc).__name__, detail=str(exc)[:512]))
        return GUARDIAN_FAILED
    finally:
        with contextlib.suppress(OSError):
            connection.close()
        watcher.close()
        watchers.close()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guardian', required=True)
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        return GUARDIAN_FAILED
    return run(args.guardian)


if __name__ == '__main__':
    code = main()
    sys.exit(code if code >= 0 else 128 - code)
