"""Portable checks for the Darwin launchd-coalition backend.

These exercise validation, protocol and census logic on any host without
touching launchd. Native macOS behaviour is covered by the separate
acceptance harness (``tools/macos_native_acceptance.py``); the two
``darwin``-only tests here are smoke paths for the real backend.
"""

import contextlib
import io
import json
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import time
import unittest

import pytest

from nexus_connector_core.native.process import macos_process
from nexus_connector_core.native.process import macos_process_guardian as guardian
from nexus_connector_core.native.process.macos_abi import _census_with
from nexus_connector_core.native.process.preflight import (
    containment_preflight, containment_requirements)

ROOT = Path(__file__).resolve().parents[1]


class FakeAbi:
    """In-memory process table for census/stop logic."""

    SIDL, SRUN, SSLEEP, SSTOP, SZOMB = 1, 2, 3, 4, 5

    def __init__(self, processes, coalition=(1, 2), fail_enumerate=False):
        # processes: pid -> dict(birth=(s,u), status=int, member=bool)
        self.processes = processes
        self.coalition = coalition
        self.fail_enumerate = fail_enumerate

    def enumerate_pids(self):
        if self.fail_enumerate:
            raise OSError(5, 'enumeration failed')
        return sorted(self.processes)

    def identity(self, pid):
        record = self.processes.get(pid)
        if record is None:
            raise ProcessLookupError(3, 'gone')
        if record.get('denied'):
            raise PermissionError(1, 'operation not permitted')
        return dict(pid=pid, ppid=0, pgid=pid, status=record['status'],
                    birth=tuple(record['birth']))

    def coalition_pair(self, pid):
        record = self.processes.get(pid)
        if record is None:
            raise ProcessLookupError(3, 'gone')
        if record.get('denied'):
            raise PermissionError(1, 'operation not permitted')
        if not record.get('member', True):
            return (self.coalition[0] + 100, self.coalition[1] + 100)
        return self.coalition

    def coalition_members(self, pair, *, exclude=(), seen=None,
                          confirmed_dead=None):
        # Run the production census logic over this fake table.
        return _census_with(self.enumerate_pids, self.identity,
                            self.coalition_pair, pair, exclude=exclude,
                            seen=seen, confirmed_dead=confirmed_dead)


def member(pid, birth, status=FakeAbi.SSLEEP):
    return dict(birth=birth, status=status, member=True)


def stranger(pid, birth):
    """Readable process in a different coalition."""
    return dict(birth=birth, status=FakeAbi.SSLEEP, member=False)


def denied(pid, birth):
    """Foreign-uid process: identity itself is EPERM-denied."""
    return dict(birth=birth, status=FakeAbi.SSLEEP, member=False, denied=True)


class ValidationTests(unittest.TestCase):
    def test_missing_executable_refuses_before_any_launchd_call(self):
        calls = []
        original = macos_process.launchctl

        def spy(*args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, '', '')

        macos_process.launchctl = spy
        try:
            with pytest.raises(FileNotFoundError):
                macos_process.OwnedDarwinPopen(
                    ['/definitely/not/here'], cwd='/', env={})
        finally:
            macos_process.launchctl = original
        self.assertEqual(calls, [])

    def test_shell_preexec_and_pass_fds_are_refused(self):
        for kwargs in (dict(shell=True), dict(preexec_fn=lambda: None),
                       dict(executable='/bin/sh'), dict(pass_fds=(3,))):
            with self.subTest(kwargs=kwargs), pytest.raises(ValueError):
                macos_process.OwnedDarwinPopen(
                    [sys.executable, '-c', 'pass'], cwd='/', env={},
                    **kwargs)

    def test_non_pipe_streams_and_relative_cwd_are_refused(self):
        with pytest.raises(ValueError):
            macos_process.OwnedDarwinPopen([sys.executable], cwd='/',
                                           env={}, stdin=subprocess.DEVNULL)
        with pytest.raises(ValueError):
            macos_process.OwnedDarwinPopen([sys.executable], cwd='rel',
                                           env={})
        with pytest.raises(ValueError):
            macos_process.OwnedDarwinPopen([sys.executable], cwd='/',
                                           env=[])

    def test_unexpected_options_are_refused(self):
        with pytest.raises(ValueError, match='unsupported'):
            macos_process.OwnedDarwinPopen([sys.executable], cwd='/', env={},
                                           user='nobody')


class PlistTests(unittest.TestCase):
    def test_job_is_one_shot_and_carries_no_environment(self):
        plist = macos_process.job_plist(
            'ai.oktolabs.nexus-owned.test', '/usr/bin/python3',
            '/g.py', '/config.json', '/out.log', '/err.log')
        self.assertIs(plist['KeepAlive'], False)
        self.assertIs(plist['RunAtLoad'], True)
        self.assertEqual(plist['ProgramArguments'],
                         ['/usr/bin/python3', '-I', '/g.py',
                          '--guardian', '/config.json'])
        self.assertNotIn('EnvironmentVariables', plist)

    def test_labels_are_unique_per_launch(self):
        labels = {macos_process.new_job_label() for _ in range(64)}
        self.assertEqual(len(labels), 64)
        self.assertTrue(all(label.startswith('ai.oktolabs.nexus-owned.')
                            for label in labels))


class CoalitionRefusalTests(unittest.TestCase):
    def test_any_shared_type_is_refused(self):
        # resource shared with caller
        self.assertTrue(guardian.coalition_conflict((1, 2), (1, 9), (3, 4)))
        # jetsam shared with caller
        self.assertTrue(guardian.coalition_conflict((1, 2), (9, 2), (3, 4)))
        # resource shared with launchd
        self.assertTrue(guardian.coalition_conflict((3, 2), (9, 8), (3, 4)))
        # jetsam shared with launchd
        self.assertTrue(guardian.coalition_conflict((1, 4), (9, 8), (3, 4)))

    def test_distinct_pairs_are_accepted(self):
        self.assertFalse(guardian.coalition_conflict((5, 6), (1, 2), (3, 4)))


class CensusTests(unittest.TestCase):
    def test_members_zombies_and_self_exclusion(self):
        abi = FakeAbi({
            10: member(10, (1, 1)),
            11: member(11, (2, 2), status=FakeAbi.SZOMB),
            12: stranger(12, (3, 3)),
            13: member(13, (4, 4), status=FakeAbi.SSTOP),
        })
        result = guardian.census(abi, (1, 2), exclude={10})
        self.assertEqual(result.members, [(13, (4, 4))])
        self.assertFalse(result.incomplete)
        self.assertEqual(result.foreign_denied, 0)

    def test_enumeration_failure_is_never_empty(self):
        abi = FakeAbi({10: member(10, (1, 1))}, fail_enumerate=True)
        self.assertIsNone(guardian.census(abi, (1, 2), exclude=set()))

    def test_previously_seen_member_becoming_denied_blocks_proof(self):
        seen = {10: (1, 1)}
        abi = FakeAbi({10: denied(10, (1, 1))})
        result = guardian.census(abi, (1, 2), exclude=set(), seen=seen)
        self.assertTrue(result.incomplete)
        self.assertEqual(result.members, [])

    def test_confirmed_death_then_denied_is_a_recycled_pid(self):
        seen = {10: (1, 1)}
        abi = FakeAbi({10: denied(10, (8, 8))})
        result = guardian.census(abi, (1, 2), exclude=set(), seen=seen,
                                 confirmed={10})
        self.assertFalse(result.incomplete)
        self.assertEqual(result.members, [])
        self.assertEqual(result.recycled_after_death, 1)
        self.assertNotIn(10, seen)

    def test_denied_stranger_without_history_is_skipped(self):
        abi = FakeAbi({10: denied(10, (9, 9))})
        result = guardian.census(abi, (1, 2), exclude=set())
        self.assertFalse(result.incomplete)
        self.assertEqual(result.foreign_denied, 1)


class StopProofTests(unittest.TestCase):
    def test_two_consecutive_empty_censuses_are_required(self):
        sequence = [
            FakeAbi({10: member(10, (1, 1))}),   # live member: kill pass
            FakeAbi({}),                          # first empty
            FakeAbi({11: member(11, (2, 2))}),    # straggler resets the count
            FakeAbi({}),                          # first empty again
            FakeAbi({}),                          # second empty: proven
        ]
        state = dict(index=0, stopped=[])
        original_census, original_stop = guardian.census, guardian.stop_member

        def fake_census(abi, pair, exclude, seen=None, confirmed=None):
            abi.processes = sequence[state['index']].processes
            result = original_census(abi, pair, exclude, seen, confirmed)
            state['index'] += 1
            return result

        def fake_stop(abi, pid, birth, pair):
            state['stopped'].append(pid)
            abi.processes.pop(pid, None)
            return 'killed'

        stats = dict(rounds=0, incomplete_passes=0, killed=0, gone=0,
                     skipped=0, suspect=0, termed=0, foreign_denied=0)
        original_sleep = guardian.time.sleep
        guardian.census, guardian.stop_member = fake_census, fake_stop
        guardian.time.sleep = lambda *_: None
        try:
            abi = FakeAbi({})
            proven = guardian.force_drain(abi, (1, 2), set(), stats, {})
        finally:
            guardian.census, guardian.stop_member = original_census, original_stop
            guardian.time.sleep = original_sleep
        self.assertTrue(proven)
        self.assertEqual(state['stopped'], [10, 11])
        self.assertEqual(stats['killed'], 2)
        self.assertGreaterEqual(stats['rounds'], 5)

    def test_incomplete_passes_never_prove(self):
        # Alternating enumeration failure and empty census: the drain must
        # keep running (never return True) while scans stay incomplete.
        state = dict(index=0)

        class Empty:
            members = []
            incomplete = False
            foreign_denied = 0
            recycled_after_death = 0

        def fake_census(abi, pair, exclude, seen=None, confirmed=None):
            state['index'] += 1
            return None if state['index'] % 2 else Empty()

        class Sentinel(Exception):
            pass

        sleeps = dict(count=0)

        def bounded_sleep(_seconds):
            sleeps['count'] += 1
            if sleeps['count'] > 12:
                raise Sentinel

        stats = dict(rounds=0, incomplete_passes=0, killed=0, gone=0,
                     skipped=0, suspect=0, termed=0, foreign_denied=0)
        original_census, original_sleep = guardian.census, guardian.time.sleep
        guardian.census, guardian.time.sleep = fake_census, bounded_sleep
        try:
            with pytest.raises(Sentinel):
                guardian.force_drain(FakeAbi({}), (1, 2), set(), stats, {})
        finally:
            guardian.census, guardian.time.sleep = original_census, original_sleep
        self.assertGreaterEqual(stats['incomplete_passes'], 5)


class StopMemberTests(unittest.TestCase):
    def _patch_kill(self, fake):
        original = os.kill
        os.kill = fake
        self.addCleanup(setattr, os, 'kill', original)

    def test_suspect_recycled_target_is_reported(self):
        abi = FakeAbi({10: member(10, (1, 1), status=FakeAbi.SSTOP)})
        kills = []
        # After the SIGKILL the PID shows a different birth: recycled.

        def fake_kill(pid, sig):
            kills.append((pid, sig))
            if sig == signal.SIGKILL:
                abi.processes[10] = dict(birth=(7, 7), status=FakeAbi.SRUN,
                                         member=True)

        self._patch_kill(fake_kill)
        outcome = guardian.stop_member(abi, 10, (1, 1), (1, 2))
        self.assertEqual(outcome, 'suspect')
        self.assertEqual([sig for _pid, sig in kills],
                         [signal.SIGSTOP, signal.SIGKILL])

    def test_verified_stop_confirms_birth(self):
        abi = FakeAbi({10: member(10, (1, 1), status=FakeAbi.SSTOP)})
        kills = []

        def fake_kill(pid, sig):
            kills.append(sig)
            if sig == signal.SIGKILL:
                abi.processes[10]['status'] = FakeAbi.SZOMB

        self._patch_kill(fake_kill)
        outcome = guardian.stop_member(abi, 10, (1, 1), (1, 2))
        self.assertEqual(outcome, 'killed')
        self.assertEqual(kills, [signal.SIGSTOP, signal.SIGKILL])


class StreamWrappingTests(unittest.TestCase):
    def test_binary_streams_match_popen_types(self):
        fds = []
        for _ in range(3):
            read, write = os.pipe()
            fds.append((read, write))
        try:
            stdin, stdout, stderr = macos_process.wrap_streams(
                fds[0][1], fds[1][0], fds[2][0])
            self.assertIsInstance(stdin, io.BufferedWriter)
            self.assertIsInstance(stdout, io.BufferedReader)
            self.assertIsInstance(stderr, io.BufferedReader)
            stdin.close(); stdout.close(); stderr.close()
        finally:
            for read, write in fds:
                for fd in (read, write):
                    with contextlib.suppress(OSError):
                        os.close(fd)

    def test_text_streams_expose_the_binary_buffer(self):
        read, write = os.pipe()
        try:
            stdin, stdout, _stderr = macos_process.wrap_streams(
                write, read, write, text_mode=True, encoding='utf-8', bufsize=1)
            self.assertIsInstance(stdin, io.TextIOWrapper)
            self.assertIsInstance(stdout, io.TextIOWrapper)
            self.assertIsInstance(stdout.buffer, io.BufferedReader)
            stdin.write('ok\n')
            stdin.flush()
            self.assertEqual(stdout.read(3), 'ok\n')
            for stream in (stdin, stdout, _stderr):
                with contextlib.suppress(OSError):
                    stream.close()
        finally:
            for fd in (read, write):
                with contextlib.suppress(OSError):
                    os.close(fd)


class PreflightTests(unittest.TestCase):
    def test_darwin_requirement_keys_are_stable(self):
        self.assertEqual(containment_requirements('darwin'),
                         ('coalition_abi', 'proc_identity', 'kqueue',
                          'launchctl', 'session_domain'))

    def test_preflight_reports_every_darwin_requirement(self):
        status = containment_preflight(platform='darwin')
        self.assertEqual(set(status), set(containment_requirements('darwin')))
        # On a non-Darwin host every value must be a diagnostic, never ok.
        if sys.platform != 'darwin':
            self.assertTrue(all(value != 'ok' for value in status.values()))


@unittest.skipUnless(sys.platform == 'darwin' and
                     containment_preflight().get('session_domain') == 'ok',
                     'native macOS GUI session required')
class NativeSmokeTests(unittest.TestCase):
    def test_owned_terminate_proves_stop(self):
        from nexus_connector_core.native.process import (
            observe_owned_process, owned_tree_census, spawn_owned_process)
        process = spawn_owned_process(
            (sys.executable, '-I', '-c',
             'import sys, time; print("up", flush=True); time.sleep(60)'),
            cwd='/tmp', env=dict(os.environ), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'up')
            census = owned_tree_census(process)
            self.assertEqual(census['count'], 1)
            process.terminate()
            self.assertEqual(process.wait(timeout=15), -15)
            self.assertTrue(observe_owned_process(process)['stop_observed'])
            self.assertEqual(owned_tree_census(process)['count'], 0)
        finally:
            process.kill()
            process.wait(timeout=15)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_owned_census_contains_setsid_orphan(self):
        from nexus_connector_core.native.process import (
            owned_tree_census, spawn_owned_process)
        escape = ('import os, time\n'
                  'pid = os.fork()\n'
                  'if pid == 0:\n'
                  '    pid2 = os.fork()\n'
                  '    if pid2 == 0:\n'
                  '        os.setsid()\n'
                  '        time.sleep(60)\n'
                  '    os._exit(0)\n'
                  'os.waitpid(pid, 0)\n'
                  'time.sleep(60)\n')
        process = spawn_owned_process(
            (sys.executable, '-I', '-c', escape), cwd='/tmp',
            env=dict(os.environ), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while (owned_tree_census(process)['count'] < 2
                   and time.monotonic() < deadline):
                time.sleep(0.05)
            pids = owned_tree_census(process)['pids']
            self.assertEqual(len(pids), 2)
            process.kill()
            process.wait(timeout=15)
            self.assertTrue(process.tree_stopped)
            from nexus_connector_core.native.process.macos_abi import coalition_members
            result = coalition_members(
                process._coalition_pair, exclude={process._guardian_pid})
            self.assertEqual(result.members, [])
        finally:
            process.kill()
            process.wait(timeout=15)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()


def time_monotonic():
    return time.monotonic()


if __name__ == '__main__':
    unittest.main()
