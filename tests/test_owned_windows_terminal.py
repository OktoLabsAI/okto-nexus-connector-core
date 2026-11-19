"""The observer cursor and the Windows terminal process have independent lifetimes."""

import json
import os
import subprocess
import sys
import time

import pytest

from nexus_connector_core import CoreError, ProcessBirthEvidence
from nexus_connector_core.native.process import observe_recorded_process_birth
from nexus_connector_core.native.process import windows_terminal

_EXITED = {"NOT_RUNNING", "NOT_OBSERVED", "DIFFERENT_BIRTH"}


def _read_until(terminal, cursor, marker):
    data = bytearray()
    deadline = time.monotonic() + 15
    while marker not in data and time.monotonic() < deadline:
        try:
            frame = terminal.read_output(cursor, timeout=0.5)
        except TimeoutError:
            continue
        assert frame is not None
        cursor = frame.sequence
        data.extend(frame.data)
    assert marker in data
    return cursor


@pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY and Job Object contract")
def test_terminal_keeps_exact_owner_and_drains_without_a_reader(tmp_path):
    script = (
        'import sys\n'
        'assert sys.stdin.isatty() and sys.stdout.isatty()\n'
        'print("viewer-initial-marker", flush=True)\n'
        'assert input() == "authorized"\n'
        'print("result-without-a-viewer", flush=True)\n'
        'assert input() == "close"\n'
    )
    births = []
    owned = windows_terminal.OwnedWindowsTerminal(
        (sys.executable, "-u", "-c", script), cwd=str(tmp_path), env=dict(os.environ), birth_observer=births.append)
    try:
        cursor = _read_until(owned, 0, b"viewer-initial-marker")
        birth, = births
        assert owned.birth == birth
        assert observe_recorded_process_birth(birth) == "MATCHING_LIVE"

        # Abandon the first cursor and let the host drive work with no reader.
        owned.write(b"authorized\r")
        assert _read_until(owned, cursor, b"result-without-a-viewer") > cursor
        assert owned.birth == birth and owned.poll() is None
        assert _read_until(owned, 0, b"result-without-a-viewer") > cursor
        owned.write(b"close\r")
        assert owned.wait(15) == 0
    finally:
        owned.close()
    assert owned.close() == 0
    assert observe_recorded_process_birth(birth) in _EXITED


def test_replay_refuses_cursors_behind_the_retained_bytes(monkeypatch):
    monkeypatch.setattr(windows_terminal, "_REPLAY_BYTES", 5)
    replay = windows_terminal._OutputReplay()
    replay.append(b"abc")
    replay.append(b"def")
    with pytest.raises(CoreError, match="SESSION_CONFLICT") as expired:
        replay.read(0, 0)
    assert expired.value.stage == "owned_terminal_cursor_expired"
    assert replay.read(1, 0) == windows_terminal.TerminalFrame(2, b"def")
    with pytest.raises(TimeoutError):
        replay.read(2, 0)
    replay.end(failed=False)
    assert replay.read(2, 0) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object kill-on-close")
def test_owner_crash_reaps_the_pseudoconsole_child(tmp_path):
    script = (
        'import json, os, sys\n'
        'from dataclasses import asdict\n'
        'from pathlib import Path\n'
        'from nexus_connector_core.native.process.windows_terminal import OwnedWindowsTerminal\n'
        'terminal = OwnedWindowsTerminal((sys.executable, "-c", "import time; time.sleep(60)"),\n'
        '                                cwd=os.getcwd(), env=dict(os.environ))\n'
        'temporary = Path("birth.tmp")\n'
        'temporary.write_text(json.dumps(asdict(terminal.birth)), encoding="utf-8")\n'
        'temporary.rename("birth.json")\n'
        'sys.stdin.readline()\n'
        'os._exit(91)\n'
    )
    with subprocess.Popen([sys.executable, "-c", script], cwd=tmp_path, stdin=subprocess.PIPE) as host:
        try:
            marker = tmp_path / "birth.json"
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                assert host.poll() is None
                time.sleep(.02)
            birth = ProcessBirthEvidence(**json.loads(marker.read_text(encoding="utf-8")))
            assert observe_recorded_process_birth(birth) == "MATCHING_LIVE"
            host.stdin.write(b"crash\n")
            host.stdin.flush()
            assert host.wait(10) == 91
            deadline = time.monotonic() + 10
            while observe_recorded_process_birth(birth) not in _EXITED and time.monotonic() < deadline:
                time.sleep(.02)
            assert observe_recorded_process_birth(birth) in _EXITED
        finally:
            if host.poll() is None:
                host.kill()
                host.wait(10)
