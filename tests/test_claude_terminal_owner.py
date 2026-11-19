import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from nexus_connector_core import ProcessBirthEvidence
from nexus_connector_core.native.claude_saved_history import ClaudeSavedHistory, claude_history_path
from nexus_connector_core.native.claude_terminal_owner import (
    observe_claude_finished_turn,
    observe_claude_interrupted_turn,
    observe_claude_terminal_idle_since,
    observe_claude_terminal_owner,
)
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
        "cwd": str(workspace), "kind": "interactive", "entrypoint": "cli", "version": "2.1.328",
        "status": "idle", "statusUpdatedAt": 1771556000000,
    }
    location = home / "sessions" / f"{birth.pid}.json"
    location.write_text(json.dumps(record), encoding="utf-8")
    return SimpleNamespace(location=location, record=record, terminal=terminal, history=history, birth=birth)


def test_registry_agrees_with_the_held_process_and_saved_state(registry):
    assert observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)
    assert observe_claude_terminal_idle_since(registry.terminal, registry.history, registry.birth) == 1771556000000
    registry.terminal.poll.side_effect = [None, 0]
    assert not observe_claude_terminal_owner(registry.terminal, registry.history, registry.birth)


@pytest.mark.parametrize(("field", "value"), [
    ("pid", 4243), ("procStart", "1"), ("sessionId", str(uuid4())), ("cwd", "other-project"),
    ("kind", "background"), ("entrypoint", "sdk-cli"), ("version", "2.1.329"), ("status", "busy"),
    ("statusUpdatedAt", None), ("statusUpdatedAt", "1771556000000"), ("statusUpdatedAt", True),
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


def test_finished_success_needs_an_exact_latest_flushed_turn(registry):
    history = registry.history
    transcript = claude_history_path(history.state_home, history.session_uuid, history.workspace)
    transcript.parent.mkdir(parents=True)
    prefix = b'{"type":"saved-fixture"}\n'
    transcript.write_bytes(prefix)
    history = replace(history, file_identity=file_identity(transcript.stat()), byte_size=len(prefix))
    scope = {"cwd": history.workspace, "sessionId": history.session_uuid, "isSidechain": False}
    assistant = scope | {"type": "assistant", "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "Final answer"}]}}
    turn_end = scope | {"type": "system", "subtype": "turn_duration",
                        "isMeta": False, "timestamp": "2026-02-20T03:33:20.001Z"}
    expected = hashlib.sha256(b"Final answer").hexdigest()

    def append(record):
        with transcript.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")

    def read(digest=expected):
        return observe_claude_finished_turn(registry.terminal, history, registry.birth, digest)

    append(assistant)
    assert read() is None
    append(turn_end)
    assert read() == 1771556000000
    assert read(hashlib.sha256(b"Intermediate answer").hexdigest()) is None
    append(assistant | {"isApiErrorMessage": True})
    assert read() is None
    assert read(None) == 1771556000000


def test_interrupt_requires_the_latest_native_abort_and_its_exact_admitted_prompt(registry):
    history = registry.history
    transcript = claude_history_path(history.state_home, history.session_uuid, history.workspace)
    transcript.parent.mkdir(parents=True)
    prefix = b'{"type":"saved-fixture"}\n'
    transcript.write_bytes(prefix)
    history = replace(history, file_identity=file_identity(transcript.stat()), byte_size=len(prefix))
    scope = {"cwd": history.workspace, "sessionId": history.session_uuid, "isSidechain": False,
             "version": "2.1.328", "entrypoint": "cli"}
    prompt_id = str(uuid4())
    prompt = scope | {"type": "user", "promptId": prompt_id, "permissionMode": "plan", "promptSource": "typed",
                      "message": {"role": "user", "content": "Original prompt"}}
    partial = scope | {"type": "assistant", "uuid": str(uuid4()), "isAbortedMidStream": True,
                       "message": {"role": "assistant", "id": "msg_original"}}
    marker = scope | {"type": "user", "promptId": prompt_id, "interruptedMessageId": "msg_original",
                      "parentUuid": partial["uuid"], "timestamp": "2026-02-20T03:33:20.001Z",
                      "message": {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}}
    expected = hashlib.sha256(b"Original prompt").digest()

    def publish(*records):
        transcript.write_bytes(prefix + b"".join(json.dumps(record).encode() + b"\n" for record in records))

    def read(digest=expected, admitted=1771555999000):
        return observe_claude_interrupted_turn(registry.terminal, history, registry.birth, prompt_id, digest, admitted)

    publish(prompt, partial, marker)
    assert read() == 1771556000000
    assert read(hashlib.sha256(b"Different prompt").digest()) is None
    assert read(admitted=1771556000000) is None
    publish(prompt, partial, marker, prompt | {"promptId": str(uuid4())})
    assert read() is None
    publish(prompt, partial | {"isAbortedMidStream": False}, marker)
    assert read() is None
    publish(prompt, partial, marker | {"interruptedMessageId": "msg_other"})
    assert read() is None
    publish(prompt, partial, marker | {"promptId": str(uuid4())})
    assert read() is None
    publish(prompt, partial, marker)
    registry.terminal.poll.side_effect = [None, None, None, 0]
    assert read() is None
