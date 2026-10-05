"""Portable checks for the native experiment; these do not qualify macOS."""
import array
import contextlib
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest

path = Path(__file__).resolve().parents[1] / 'tools/macos_launchd_probe.py'
spec = importlib.util.spec_from_file_location('launchd_probe', path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AbiTests(unittest.TestCase):
    def query(self, count, values=(201, 202)):
        class Library:
            def proc_pidinfo(self, pid, flavor, offset, pointer, size):
                assert (pid, flavor, offset, size) == (123, 20, 0, 40)
                pointer._obj.ids[:] = values
                return count
        return Library()

    def test_exact_abi_returns_both_ids(self):
        self.assertEqual(ctypes.sizeof(probe.CoalitionInfo), 40)
        self.assertEqual(probe.coalition_of(self.query(40), 123), (201, 202))

    def test_partial_or_future_abi_refuses_membership(self):
        for count in (-1, 0, 8, 16, 32, 39, 41, 64):
            with self.subTest(count=count), self.assertRaises(OSError):
                probe.coalition_of(self.query(count), 123)

    def test_missing_coalition_refuses_membership(self):
        for values in ((0, 0), (201, 0), (0, 202)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                probe.coalition_of(self.query(40, values), 123)

    def test_job_is_one_shot_and_only_runs_isolated_probe(self):
        result = probe.job_plist('ai.oktolabs.nexus-pipes-probe.test', '/tmp/config', '/tmp/out', '/tmp/err')
        self.assertIs(result['KeepAlive'], False)
        self.assertIs(result['RunAtLoad'], True)
        self.assertEqual(result['ProgramArguments'][1:], ['-I', str(path), '--guardian', '/tmp/config'])
        self.assertNotIn('EnvironmentVariables', result)

    @unittest.skipIf(sys.platform == 'darwin', 'Non-Mac refusal check')
    def test_non_mac_refuses_before_job_or_fixture(self):
        result = subprocess.run([sys.executable, '-I', str(path), '--run-native'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'UNSUPPORTED_TEST_HOST')
        self.assertFalse(report['containment_qualified'])
        self.assertFalse(report['provider_execution'])
        self.assertFalse(report['tree_stop_proven'])
        self.assertNotIn('scenarios', report)


@unittest.skipUnless(hasattr(socket, 'SCM_RIGHTS') and hasattr(os, 'fork'), 'Unix descriptor handoff required')
class PipeTests(unittest.TestCase):
    def test_fixed_fixture_native_pipe_handoff_and_descriptor_hygiene(self):
        native = subprocess.Popen([sys.executable, '-I', '-c', probe.FIXTURE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, start_new_session=True)
        received = []
        left, right = socket.socketpair()
        left.settimeout(3)
        right.settimeout(3)
        try:
            probe.send_pipes(left, 'fixture-token', native.pid,
                             [native.stdin.fileno(), native.stdout.fileno(), native.stderr.fileno()])
            for stream in (native.stdin, native.stdout, native.stderr):
                stream.close()
            pid, received = probe.receive_pipes(right, 'fixture-token')
            self.assertEqual(pid, native.pid)
            self.assertTrue(all(not os.get_inheritable(fd) for fd in received))
            os.write(received[0], b'nexus-native-pipe-check\n')
            frames = {row['kind']: row for row in map(json.loads, probe.read_lines(received[1], 3))}
            self.assertEqual(frames['echo']['message'], 'nexus-native-pipe-check')
            self.assertEqual(frames['leader']['extra_fds'], [])
            self.assertEqual(frames['grandchild']['extra_fds'], [])
            self.assertEqual(probe.read_lines(received[2], 1), ['native-stderr-marker'])
        finally:
            for fd in received:
                os.close(fd)
            left.close()
            right.close()
            if native.poll() is None:
                native.kill()
            native.wait(timeout=5)
            for stream in (native.stdin, native.stdout, native.stderr):
                stream.close()

    def test_fragmented_control_metadata_is_reassembled(self):
        left, right = socket.socketpair()
        originals = [os.open(os.devnull, os.O_RDWR) for _ in range(3)]
        received = []
        try:
            right.settimeout(3)
            data = json.dumps(dict(token='expected', native_pid=123)).encode() + b'\n'
            left.sendmsg([data[:4]], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', originals))])
            left.sendall(data[4:])
            _, received = probe.receive_pipes(right, 'expected')
            self.assertEqual(len(received), 3)
        finally:
            left.close()
            right.close()
            for fd in originals + received:
                os.close(fd)

    def test_rejected_handoff_closes_received_fds(self):
        # A fake recvmsg exposes actual descriptors so their closure is directly
        # observable, without relying on process-wide descriptor counts.
        for mode in ('token', 'count', 'truncated', 'malformed'):
            with self.subTest(mode=mode):
                descriptors = [os.open(os.devnull, os.O_RDWR) for _ in range(2 if mode == 'count' else 3)]
                class Connection:
                    def recvmsg(self, *_):
                        data = b'bad json\n' if mode == 'malformed' else json.dumps(dict(
                            token='wrong' if mode == 'token' else 'expected', native_pid=123)).encode() + b'\n'
                        return data, [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', descriptors).tobytes())], socket.MSG_CTRUNC if mode == 'truncated' else 0, None
                try:
                    with self.assertRaises(ValueError):
                        probe.receive_pipes(Connection(), 'expected')
                    for fd in descriptors:
                        with self.assertRaises(OSError):
                            os.fstat(fd)
                finally:
                    for fd in descriptors:
                        with contextlib.suppress(OSError):
                            os.close(fd)


if __name__ == '__main__':
    unittest.main()
