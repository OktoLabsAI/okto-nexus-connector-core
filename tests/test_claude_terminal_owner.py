import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from nexus_connector_core import ProcessBirthEvidence
from nexus_connector_core.native.claude_saved_history import ClaudeSavedHistory
from nexus_connector_core.native.claude_terminal_owner import observe_claude_terminal_owner
from nexus_connector_core.native.saved_history_file import file_identity


@pytest.fixture
def registry(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "state"
    workspace.mkdir()
    (home / "sessions").mkdir(parents=True)
    history = ClaudeSavedHistory(str(uuid4()), str(home), str(workspace), file_identity(home.stat()),
                                file_identity(workspace.stat()), (1, 2), 100, "0" * 64)
    birth = ProcessBirthEvidence("win32", 4242, "filetime:01d123abc4567890", "windows_job")
    terminal = Mock(spec=["poll", "birth"])
    terminal.poll.return_value = None
    terminal.birth = birth
    record = {
        "pid": birth.pid, "procStart": str(int("01d123abc4567890", 16)), "sessionId": history.session_uuid,
        "cwd": str(workspace), "kind": "interactive", "entrypoint": "cli", "version": "2.1.328", "status": "idle",
    }
    location = home / "sessions" / f"{birth.pid}.json"
    location.write_text(json.dumps(record), encoding="utf-8")
    return SimpleNamespace(location=location, record=record, terminal=terminal, history=history, birth=birth)


def test_registry_agrees_with_the_held_process_and_saved_state(registry):
    assert observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)
    registry.terminal.poll.side_effect = [None, 0]
    assert not observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)


@pytest.mark.parametrize(("field", "value"), [
    ("pid", 4243), ("procStart", "1"), ("sessionId", str(uuid4())), ("cwd", "other-project"),
    ("kind", "background"), ("entrypoint", "sdk-cli"), ("version", "2.1.329"), ("status", "busy"),
])
def test_registry_refuses_each_identity_drift(registry, field, value):
    registry.location.write_text(json.dumps(registry.record | {field: value}), encoding="utf-8")
    assert not observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)


def test_registry_refuses_unstable_or_unbounded_metadata(registry):
    assert not observe_claude_terminal_owner(registry.terminal,
        replace(registry.history, home_identity=(0, 0)), registry.birth)
    registry.location.write_bytes(b" " * (64 * 1024 + 1))
    assert not observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)
    registry.location.write_bytes(b'{"pid": 4242, "pid": 4242}')
    assert not observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)
    registry.location.unlink()
    assert not observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)


def test_registry_cannot_replace_the_held_handle(registry):
    registry.terminal.birth = replace(registry.birth, birth_token="filetime:01d123abc4567891")
    assert not observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)
