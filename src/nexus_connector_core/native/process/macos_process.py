"""Darwin launchd-coalition-owned subprocesses, one guardian job per launch.

The owned native process is *not* a child of this process: it is spawned by
an isolated launchd guardian job (``RunAtLoad=true``, ``KeepAlive=false``)
whose coalition pair is the ownership key for the whole tree, including
descendants that escape through ``setsid``/double-fork. This module is the
observer side; the containment logic lives in
``macos_process_guardian.py`` (see its ownership contract).

The returned object duck-types the ``subprocess.Popen`` surface the runtime
uses (``pid``/``args``/``stdin``/``stdout``/``stderr``/``poll``/``wait``/
``terminate``/``kill``/``returncode``): the three pipes are handed over
AF_UNIX ``SCM_RIGHTS`` and wrapped exactly like ``Popen`` wraps its own
pipes, so text/binary semantics are unchanged for callers.

Lifecycle mirrors the qualified Linux backend:

- one of 32 class-level slots is retained until a proven stop ("D") is
  observed; unresolved trees keep their slot;
- ``terminate()`` requests a SIGTERM pass; ``kill()`` escalates to the
  force drain; both leave the proof protocol intact;
- the death of this whole process closes the control connection, which the
  guardian treats as force escalation followed by its proof attempt;
- ``launchctl bootout`` is only ever label cleanup, never stop evidence.
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from .macos_abi import coalition_pair, identity

ACCEPT_TIMEOUT_SECONDS = 10.0
HANDOFF_TIMEOUT_SECONDS = 5.0
LAUNCHCTL_TIMEOUT_SECONDS = 8.0
GUARDIAN_LOST_EXITCODE = 125

#: Only ``gui/<uid>`` is qualified (native evidence 2026-10-02: gui/501
#: completed all scenarios; user/501 bootstrap returned error 5). Refusing
#: instead of silently claiming headless support is part of the contract.
QUALIFIED_DOMAIN = 'gui'

_PIPE_KEYS = ('stdin', 'stdout', 'stderr')


def _trace(event: str, **details) -> None:
    """Optional lifecycle trace (env NXOWN_TRACE=path); off by default."""
    path = os.environ.get('NXOWN_TRACE')
    if not path:
        return
    import json as _json
    with open(path, 'a', encoding='utf-8') as stream:
        stream.write(_json.dumps(
            dict(event=event, pid=os.getpid(), monotonic=round(time.monotonic(), 3),
                 **details)) + '\n')


def launchctl(*args, timeout: float = LAUNCHCTL_TIMEOUT_SECONDS):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True,
                          text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, close_fds=True)


def new_job_label() -> str:
    """Unique per-launch label; never reused across sessions."""
    return f'ai.oktolabs.nexus-owned.{os.getpid()}.{secrets.token_hex(8)}'


def job_plist(label: str, python: str, guardian: str, config,
              stdout, stderr) -> dict:
    """One-shot guardian job description; no environment is embedded."""
    return dict(Label=label,
                ProgramArguments=[python, '-I', guardian,
                                  '--guardian', str(config)],
                RunAtLoad=True, KeepAlive=False, ProcessType='Background',
                StandardOutPath=str(stdout), StandardErrorPath=str(stderr))


def wrap_streams(stdin_fd: int, stdout_fd: int, stderr_fd: int, *,
                  bufsize: int = -1, text_mode: bool = False,
                  encoding=None, errors=None):
    """Wrap received descriptors exactly like ``subprocess.Popen`` does."""
    # CPython Popen: binary streams never line-buffer; bufsize==1 only
    # selects line buffering on the text wrapper.
    if bufsize == 1:
        line_buffering = True
        bufsize = -1
    else:
        line_buffering = False
    stdin = io.open(stdin_fd, 'wb', bufsize)
    stdout = io.open(stdout_fd, 'rb', bufsize)
    stderr = io.open(stderr_fd, 'rb', bufsize)
    if text_mode:
        stdin = io.TextIOWrapper(stdin, write_through=True,
                                 line_buffering=line_buffering,
                                 encoding=encoding, errors=errors)
        stdout = io.TextIOWrapper(stdout, encoding=encoding, errors=errors)
        stderr = io.TextIOWrapper(stderr, encoding=encoding, errors=errors)
    return stdin, stdout, stderr


class OwnedDarwinPopen:
    """Observer handle for one launchd-coalition-owned process tree."""

    _slots = threading.BoundedSemaphore(32)

    def __init__(self, argv, **kwargs):
        if sys.platform != 'darwin':
            raise RuntimeError(
                'Darwin process ownership requires the launchd coalition backend')
        argv = list(argv)
        if isinstance(argv, (str, bytes)) or any(
                kwargs.get(key) for key in ('shell', 'preexec_fn', 'executable')):
            raise ValueError('Owned Darwin processes require argv without '
                             'shell/preexec overrides')
        if kwargs.get('pass_fds'):
            raise ValueError('Extra inherited descriptors are not supported')
        for stream in _PIPE_KEYS:
            if kwargs.get(stream, subprocess.PIPE) != subprocess.PIPE:
                raise ValueError('owned launch requires three separate pipes')
        if not kwargs.get('cwd') or not os.path.isabs(kwargs['cwd']):
            raise ValueError('owned launch needs local absolute cwd')
        if not isinstance(kwargs.get('env'), dict):
            raise ValueError('owned launch requires an explicit environment')
        if kwargs.get('close_fds') not in (None, True):
            raise ValueError('descriptor closing cannot be disabled')
        unexpected = (set(kwargs) - {'cwd', 'env', *_PIPE_KEYS, 'bufsize',
                                     'text', 'universal_newlines', 'encoding',
                                     'errors', 'start_new_session',
                                     'close_fds', 'max_tree_processes'})
        if unexpected:
            raise ValueError(f'unsupported owned-launch options: '
                             f'{", ".join(sorted(unexpected))}')
        if not argv:
            raise ValueError('An executable is required')
        executable = os.fspath(argv[0])
        if os.path.dirname(executable):
            resolved = os.path.join(kwargs.get('cwd') or os.curdir, executable)
        else:
            resolved = shutil.which(
                executable, path=(kwargs.get('env') or {}).get('PATH', os.defpath))
        if resolved is None or not os.path.exists(resolved):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT),
                                    executable)
        if not os.path.isfile(resolved) or not os.access(resolved, os.X_OK):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES),
                                  executable)
        argv[0] = os.path.abspath(resolved)
        self.args = list(argv)
        self._requested_tree_limit = kwargs.pop('max_tree_processes', None)
        if self._requested_tree_limit is not None and (
                type(self._requested_tree_limit) is not int or
                self._requested_tree_limit < 1):
            raise ValueError('invalid owned tree process limit')
        self._text_settings = dict(
            bufsize=kwargs.get('bufsize', -1),
            text_mode=bool(kwargs.get('text') or kwargs.get('universal_newlines')),
            encoding=kwargs.get('encoding'), errors=kwargs.get('errors'))
        self._ownership_lock = threading.Lock()
        self._pump_lock = threading.RLock()
        self._finished = False
        self.tree_stopped = False
        self.returncode = None
        self.pid = 0
        self.stdin = self.stdout = self.stderr = None
        self._control = None
        self._listener = None
        self._root = None
        self._service = None
        self._coalition_pair = None
        self._guardian_pid = None
        self._token = None
        self._buffer = b''
        self._failure_detail = None
        self._owns_slot = type(self)._slots.acquire(blocking=False)
        if not self._owns_slot:
            raise RuntimeError('Darwin owned-process capacity exhausted; '
                               'unresolved trees retain their slots')
        try:
            self._launch(argv, kwargs['cwd'], kwargs['env'])
        except BaseException:
            self._abandon()
            self._release_slot()
            raise

    # ------------------------------------------------------------------ #
    # launch and handoff

    def _launch(self, argv, cwd, env):
        self._root = Path(tempfile.mkdtemp(prefix='nxown-', dir='/tmp'))
        os.chmod(self._root, 0o700)
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(self._root / 'control.sock'))
        self._listener.listen(1)
        self._listener.settimeout(ACCEPT_TIMEOUT_SECONDS)
        self._token = secrets.token_hex(32)
        self._label = new_job_label()
        caller_pair = coalition_pair(os.getpid())
        config = dict(socket=str(self._root / 'control.sock'),
                      token=self._token, owner_pid=os.getpid(),
                      owner_birth=list(identity(os.getpid())['birth']),
                      caller_coalition=list(caller_pair),
                      argv=list(argv), cwd=cwd, env=dict(env))
        config_path = self._root / 'config.json'
        config_path.write_text(json.dumps(config), encoding='utf-8')
        os.chmod(config_path, 0o600)
        plist_path = self._root / 'job.plist'
        python = str(Path(sys.executable).resolve())
        guardian = str(Path(__file__).with_name('macos_process_guardian.py'))
        plist_path.write_bytes(plistlib.dumps(job_plist(
            self._label, python, guardian, config_path,
            self._root / 'guardian.out', self._root / 'guardian.err')))
        domain = f'{QUALIFIED_DOMAIN}/{os.getuid()}'
        try:
            boot = launchctl('bootstrap', domain, str(plist_path))
        except subprocess.TimeoutExpired as exc:
            raise OSError(errno.EIO, 'launchctl bootstrap timed out') from exc
        if boot.returncode:
            raise OSError(errno.EIO, 'launchctl bootstrap refused '
                          f'{domain} (rc={boot.returncode}): '
                          f'{boot.stderr.strip()[-512:]}; a GUI login session '
                          'is required - headless/user-domain bootstrap is '
                          'not qualified')
        self._service = f'{domain}/{self._label}'
        try:
            connection, _ = self._listener.accept()
        except OSError as exc:
            raise OSError(errno.EIO,
                          f'guardian did not connect within '
                          f'{ACCEPT_TIMEOUT_SECONDS}s') from exc
        connection.settimeout(HANDOFF_TIMEOUT_SECONDS)
        descriptors = []
        try:
            frame, descriptors = self._receive(connection)
            if frame.get('kind') == 'error':
                raise self._spawn_error(frame)
            if frame.get('kind') != 'handoff':
                raise OSError(errno.EIO, 'unexpected guardian frame')
            native_pid = frame.get('pid')
            if (len(descriptors) != 3 or type(native_pid) is not int
                    or native_pid <= 1):
                raise OSError(errno.EIO,
                              'invalid descriptor handoff identity or count')
            observed = identity(native_pid)
            if tuple(observed['birth']) != tuple(frame.get('birth', ())):
                raise OSError(errno.EIO,
                              'native handoff failed birth verification')
            pair = coalition_pair(native_pid)
            if pair == caller_pair:
                raise OSError(errno.EIO,
                              'native process shares the observer coalition')
        except BaseException:
            for descriptor in descriptors:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            raise
        finally:
            with contextlib.suppress(OSError):
                self._listener.close()
            self._listener = None
        for descriptor in descriptors:
            os.set_inheritable(descriptor, False)
        self._coalition_pair = pair
        self._guardian_pid = frame['guardian_pid']
        self.pid = native_pid
        self.stdin, self.stdout, self.stderr = wrap_streams(
            *descriptors, **self._text_settings)
        self._control = connection
        _trace('handoff', native_pid=native_pid, guardian=self._guardian_pid,
               label=self._label)

    @staticmethod
    def _receive(connection):
        """Receive one framed message plus ``SCM_RIGHTS`` descriptors."""
        import array
        descriptors = []
        data = b''
        try:
            size = array.array('i').itemsize
            chunk, ancillary, flags, _ = connection.recvmsg(
                4096, socket.CMSG_SPACE(3 * size))
            unexpected = False
            for level, kind, payload in ancillary:
                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                    unexpected = True
                    continue
                received = array.array('i')
                received.frombytes(payload[:len(payload) - len(payload) % size])
                descriptors.extend(received)
                if len(payload) % size:
                    unexpected = True
            if flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC) or unexpected:
                raise OSError(errno.EIO, 'truncated descriptor handoff')
            data = chunk
            # AF_UNIX SOCK_STREAM can split normal data; read the full line.
            while not data.endswith(b'\n') and len(data) < 4096:
                part = connection.recv(4096 - len(data))
                if not part:
                    break
                data += part
            if not data.endswith(b'\n'):
                raise OSError(errno.EIO, 'unterminated guardian frame')
            frame = json.loads(data)
            if not isinstance(frame, dict):
                raise OSError(errno.EIO, 'invalid guardian frame')
            return frame, descriptors
        except BaseException:
            for descriptor in descriptors:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            raise

    @staticmethod
    def _spawn_error(frame) -> OSError:
        name = frame.get('error')
        detail = frame.get('detail') or frame.get('strerror') or \
            'native launch failed inside the guardian'
        if name == 'FileNotFoundError':
            return FileNotFoundError(frame.get('errno') or errno.ENOENT,
                                     detail, frame.get('filename'))
        if name == 'PermissionError':
            return PermissionError(frame.get('errno') or errno.EACCES,
                                   detail, frame.get('filename'))
        return OSError(frame.get('errno') or errno.EIO,
                       f'{name}: {detail} ({frame.get("stage", "unknown")})')

    # ------------------------------------------------------------------ #
    # control and observation

    def _release_slot(self):
        with self._ownership_lock:
            if self._owns_slot:
                self._owns_slot = False
                type(self)._slots.release()

    def _pump(self, timeout):
        if self._control is None or self.returncode is not None:
            return
        try:
            readable, _, _ = select_select([self._control], [], [], timeout)
        except (OSError, ValueError):
            self._finish(None)
            return
        if not readable:
            return
        try:
            data = self._control.recv(4096)
        except OSError:
            self._finish(None)
            return
        if not data:
            self._finish(None)
            return
        self._buffer += data
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            try:
                frame = json.loads(line)
            except ValueError:
                self._finish(None)
                return
            if not isinstance(frame, dict) or frame.get('token') != self._token:
                self._finish(None)
                return
            if frame.get('kind') == 'final':
                self._finish(frame)
                return
            if frame.get('kind') == 'error':
                self._failure_detail = frame
                self._finish(None)
                return

    def _finish(self, frame):
        _trace('finish', frame_kind=(frame or {}).get('kind'),
               proof=(frame or {}).get('proof'), label=self._label)
        with self._pump_lock:
            if self._finished:
                return
            self._finished = True
            if frame is not None and frame.get('proof') == 'D':
                self.tree_stopped = True
                code = frame.get('exitcode')
                self.returncode = (code if type(code) is int
                                   else GUARDIAN_LOST_EXITCODE)
            else:
                self.returncode = GUARDIAN_LOST_EXITCODE
            if self._control is not None:
                with contextlib.suppress(OSError):
                    self._control.close()
                self._control = None
        if self.tree_stopped:
            self._release_slot()
        self._remove_job()
        if self._root is not None:
            shutil.rmtree(self._root, ignore_errors=True)
            self._root = None

    def _remove_job(self):
        if self._service is not None:
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                launchctl('bootout', self._service)
            self._service = None

    def _abandon(self):
        for stream in (self.stdin, self.stdout, self.stderr):
            if stream is not None:
                with contextlib.suppress(OSError, ValueError):
                    stream.close()
        self.stdin = self.stdout = self.stderr = None
        with self._pump_lock:
            self._finished = True
            if self._control is not None:
                with contextlib.suppress(OSError):
                    self._control.close()
                self._control = None
            if self._listener is not None:
                with contextlib.suppress(OSError):
                    self._listener.close()
                self._listener = None
        self._remove_job()
        if self._root is not None:
            shutil.rmtree(self._root, ignore_errors=True)
            self._root = None

    # ------------------------------------------------------------------ #
    # subprocess.Popen-compatible surface

    def poll(self):
        with self._pump_lock:
            if self.returncode is None and not self._finished:
                self._pump(0)
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            deadline = None if timeout is None else time.monotonic() + timeout
            while self.returncode is None and not self._finished:
                remaining = (None if deadline is None
                             else max(0.0, deadline - time.monotonic()))
                with self._pump_lock:
                    if self.returncode is None and not self._finished:
                        self._pump(remaining)
                if (self.returncode is None and not self._finished
                        and deadline is not None
                        and time.monotonic() >= deadline):
                    raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def terminate(self):
        """Request a SIGTERM pass; escalation stays with ``kill()``."""
        if self._control is not None and not self._finished:
            _trace('terminate', native_pid=self.pid, label=self._label)
            try:
                self._control.sendall(b'T')
            except OSError:
                with contextlib.suppress(OSError):
                    self._control.shutdown(socket.SHUT_WR)

    def kill(self):
        """Escalate to the force drain by closing the request channel."""
        if self._control is not None and not self._finished:
            _trace('kill', native_pid=self.pid, label=self._label)
            with contextlib.suppress(OSError):
                self._control.shutdown(socket.SHUT_WR)

    def send_signal(self, sig):
        raise ValueError('owned trees are controlled only through '
                         'terminate() and kill() escalation')

    def owned_tree_pids(self, limit: int = 256) -> tuple[list[int], bool]:
        """Bounded census of the owned coalition (observability only).

        Includes descendants that escaped through ``setsid``; excludes the
        guardian itself and zombies. An unreadable scan reports ``overflow``
        rather than a trustworthy empty result. This is an observation,
        never authority to signal or adopt a PID.
        """
        if type(limit) is not int or not 1 <= limit <= 4096:
            raise ValueError('invalid census limit')
        if self._coalition_pair is None or (
                self.returncode is not None and self.tree_stopped):
            return [], False
        from .macos_abi import coalition_members
        result = coalition_members(
            self._coalition_pair, exclude={self._guardian_pid})
        pids = sorted(pid for pid, _birth in result.members)
        return pids[:limit], len(pids) > limit or result.incomplete


def select_select(read, write, exceptional, timeout):
    """Indirection so portable tests can stub the blocking wait."""
    import select
    return select.select(read, write, exceptional, timeout)
