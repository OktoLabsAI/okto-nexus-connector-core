"""Host-owned ConPTY with bounded output replay and a Windows Job Object."""

import ctypes
import math
import os
import threading
from collections import deque
from contextlib import ExitStack
from ctypes import wintypes as w
from dataclasses import dataclass

from ...models import CoreError
from .birth import record_owned_process_birth, snapshot_owned_process_birth
from .windows_process import OwnedWindowsPopen

_CHUNK_BYTES = 4096
_REPLAY_BYTES = 512 * 1024
_INPUT_BYTES = 64 * 1024
_STAGE = "owned_terminal"


class _Dimensions(ctypes.Structure):
    _fields_ = [("columns", w.SHORT), ("rows", w.SHORT)]


def _console_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreatePseudoConsole
    create.argtypes = [_Dimensions, w.HANDLE, w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    create.restype = ctypes.c_long
    close = kernel.ClosePseudoConsole
    close.argtypes = [w.HANDLE]
    close.restype = None
    return create, close


@dataclass(frozen=True, slots=True)
class TerminalFrame:
    sequence: int
    data: bytes


class _OutputReplay:
    def __init__(self):
        self._available = threading.Condition()
        self._frames = deque()
        self._sequence = 0
        self._bytes = 0
        self._ended = False
        self._failed = False

    def append(self, data):
        with self._available:
            self._sequence += 1
            self._frames.append(TerminalFrame(self._sequence, data))
            self._bytes += len(data)
            while self._bytes > _REPLAY_BYTES:
                self._bytes -= len(self._frames.popleft().data)
            self._available.notify_all()

    def end(self, *, failed):
        with self._available:
            self._ended = True
            self._failed = failed
            self._available.notify_all()

    def read(self, after_sequence, timeout):
        if (type(after_sequence) is not int or after_sequence < 0
                or type(timeout) not in (int, float) or not 0 <= timeout <= 5
                or not math.isfinite(timeout)):
            raise ValueError("Invalid terminal cursor or wait.")
        with self._available:
            if after_sequence > self._sequence:
                raise CoreError("SESSION_CONFLICT", _STAGE)
            if not self._available.wait_for(lambda: self._sequence > after_sequence or self._ended, timeout):
                raise TimeoutError("The terminal has not produced more output.")
            offset = after_sequence - (self._sequence - len(self._frames))
            if offset < 0:
                raise CoreError("SESSION_CONFLICT", "owned_terminal_cursor_expired")
            if offset < len(self._frames):
                return self._frames[offset]
            if self._failed:
                raise CoreError("NATIVE_UNAVAILABLE", _STAGE)
            return None


class OwnedWindowsTerminal:
    """Retain the process and drain its terminal independently of any reader.

    Only the host that owns the authorized execution may use `write`. A
    viewer uses `read_output` with its own cursor and has no lifecycle effect.
    """

    def __init__(self, argv, *, cwd, env, columns=110, rows=28, container_id=None, birth_observer=None):
        if os.name != "nt":
            raise CoreError("CAPABILITY_UNSUPPORTED", _STAGE)
        if (not isinstance(argv, (list, tuple)) or not argv
                or any(type(part) is not str or not part or "\0" in part for part in argv)
                or not os.path.isabs(argv[0]) or not os.path.isabs(cwd)
                or type(env) is not dict
                or any(type(key) is not str or not key or "\0" in key or "=" in key
                       or type(value) is not str or "\0" in value for key, value in env.items())
                or type(columns) is not int or not 24 <= columns <= 300
                or type(rows) is not int or not 8 <= rows <= 120):
            raise ValueError("Invalid owned terminal launch.")
        import msvcrt

        self._output = _OutputReplay()
        self._closing = threading.Event()
        self._close_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closed = False
        self._exit_code = None
        create_console, close_console = _console_api()
        with ExitStack() as owned:
            with ExitStack() as peer:
                console_input, self._input = os.pipe()
                peer.callback(os.close, console_input)
                owned.callback(self._close_input)
                output, console_output = os.pipe()
                owned.callback(os.close, output)
                peer.callback(os.close, console_output)
                console = w.HANDLE()
                result = create_console(_Dimensions(columns, rows), msvcrt.get_osfhandle(console_input),
                                        msvcrt.get_osfhandle(console_output), 0, ctypes.byref(console))
                if result < 0:
                    raise OSError("CreatePseudoConsole failed", hex(result & 0xFFFFFFFF))
                self._reader = threading.Thread(target=self._drain, args=(output,), daemon=True)
                # Keep draining while ClosePseudoConsole emits its final frame.
                owned.callback(self._join_reader)
                owned.callback(close_console, console)
                self._reader.start()
            self._process = OwnedWindowsPopen(list(argv), executable=argv[0], cwd=cwd, env=env,
                                              container_id=container_id, pseudoconsole=console)
            try:
                record_owned_process_birth(self._process, birth_observer)
            except BaseException:
                self._stop_process()
                raise
            self._resources = owned.pop_all()

    @property
    def birth(self):
        return snapshot_owned_process_birth(self._process)

    def poll(self):
        return self._process.poll()

    def wait(self, timeout=None):
        return self._process.wait(timeout)

    def _drain(self, descriptor):
        failed = False
        try:
            while data := os.read(descriptor, _CHUNK_BYTES):
                self._output.append(data)
        except OSError:
            failed = not self._closing.is_set()
        finally:
            self._output.end(failed=failed)

    def _join_reader(self):
        if self._reader.ident is None:
            return
        self._reader.join(5)
        if self._reader.is_alive():
            raise OSError("The owned terminal did not release its output pipe.")

    def _close_input(self):
        with self._write_lock:
            os.close(self._input)

    def read_output(self, after_sequence, *, timeout=1.0):
        """Return the next frame, None at EOF, or raise on timeout or an expired cursor."""
        return self._output.read(after_sequence, timeout)

    def write(self, data, *, before_write=None):
        if type(data) is not bytes or not 1 <= len(data) <= _INPUT_BYTES:
            raise ValueError("Invalid terminal input.")
        with self._write_lock:
            if self._closing.is_set() or self.poll() is not None:
                raise CoreError("NATIVE_UNAVAILABLE", _STAGE)
            if before_write is not None:
                before_write()
            remaining = memoryview(data)
            while remaining:
                size = os.write(self._input, remaining)
                if size <= 0:
                    raise OSError("The owned terminal stopped accepting input.")
                remaining = remaining[size:]

    def _stop_process(self):
        if self.poll() is None:
            self._process.terminate()
        return self.wait(10)

    def close(self):
        """Explicit owner shutdown. Reader cancellation never calls this method."""
        with self._close_lock:
            if self._closed:
                return self._exit_code
            self._closing.set()
            self._exit_code = self._stop_process()
            self._resources.close()
            self._closed = True
            return self._exit_code
