"""Exact native rollout observation. All persisted content here is synthetic."""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from nexus_connector_core.native.adapter_types import (
    HarnessCapabilities,
    HarnessSession,
)
from nexus_connector_core.native.adapters.codex import (
    CodexAppServerConnector,
    _ThreadState,
)
from nexus_connector_core.native.codex_rollout import observe_rollout


@pytest.fixture
def rollout(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "private-codex-home"
    path = home / "sessions" / "2026" / "11" / "rollout-native.jsonl"
    path.parent.mkdir(parents=True)
    thread = "private-thread"
    header = {"type": "session_meta", "payload": {"id": thread, "cwd": str(project)}}
    body = {"type": "response_item", "payload": {"text": "private-history"}}
    path.write_bytes(b"".join(json.dumps(value).encode() + b"\n" for value in (header, body)))
    return home, path, thread, project


def test_exact_rollout_is_hashed_without_exporting_path_or_history(rollout):
    home, path, thread, project = rollout
    proof = observe_rollout(str(home), str(path), thread, str(project))
    assert proof.thread_id == thread and proof.state_home == str(home)
    assert proof.relative_path == path.relative_to(home).parts
    assert proof.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert proof.byte_size == path.stat().st_size
    assert all(secret not in repr(proof) for secret in (thread, str(home), path.name, "private-history"))


@pytest.mark.parametrize("changes_during_read", [False, True])
def test_windows_style_handle_ctime_is_compared_against_the_same_source(
        rollout, monkeypatch, changes_during_read):
    home, path, thread, project = rollout
    attributes = path.stat()
    times = iter((attributes.st_ctime_ns + 1, attributes.st_ctime_ns + (2 if changes_during_read else 1)))

    def path_independent_handle(_descriptor):
        return SimpleNamespace(st_dev=attributes.st_dev, st_ino=attributes.st_ino,
                               st_size=attributes.st_size, st_mtime_ns=attributes.st_mtime_ns,
                               st_ctime_ns=next(times))

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", path_independent_handle)
        proof = observe_rollout(str(home), str(path), thread, str(project))
    assert (proof is None) == changes_during_read


@pytest.mark.parametrize("defect", ["different-thread", "different-root", "missing", "outside",
                                     "metadata-only", "unfinished", "duplicate-id", "linked"])
def test_reported_path_does_not_prove_a_saved_exact_thread(rollout, tmp_path, defect):
    home, path, thread, project = rollout
    if defect == "different-thread":
        thread = "neighbor-thread"
    elif defect == "different-root":
        project = tmp_path
    elif defect == "missing":
        path.unlink()
    elif defect == "outside":
        foreign = tmp_path / path.name
        path.rename(foreign)
        path = foreign
    elif defect == "metadata-only":
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    elif defect == "unfinished":
        path.write_bytes(path.read_bytes()[:-1])
    elif defect == "duplicate-id":
        path.write_bytes(path.read_bytes().replace(b'"id":', b'"id": "foreign", "id":'))
    elif defect == "linked":
        try:
            os.link(path, tmp_path / "same-file.jsonl")
        except OSError:
            pytest.skip("Hard links are unavailable on this test filesystem.")
    assert observe_rollout(str(home), str(path), thread, str(project)) is None


def test_owned_idle_reader_uses_realized_state_home_without_changing_presenter(rollout):
    home, path, thread, project = rollout
    connector = CodexAppServerConnector(cwd=str(project), env={"CODEX_HOME": str(home)})
    caps = HarnessCapabilities(False, None, False, False, False)
    session = HarnessSession("local", "codex", "agent", "STARTING", caps, "2026-11-18T00:00:00Z")
    state = _ThreadState(session.session_id, thread, session.owning_agent_id)
    connector._sessions_by_id[session.session_id] = state
    native = {"id": thread, "status": {"type": "idle"}, "createdAt": 1, "updatedAt": 1,
              "ephemeral": False, "path": str(path), "cwd": str(project), "turns": []}
    calls = []

    def read(method, params, *, timeout_s):
        calls.append((method, params))
        return {"thread": native}

    connector._transport = SimpleNamespace(_env={"CODEX_HOME": str(home)}, is_alive=lambda: True, request=read)
    assert connector.read_owned_rollout(session, thread).thread_id == thread
    assert connector.read_owned_thread(session, thread) == {
        "thread_id": thread, "status": "idle", "created_at": 1, "updated_at": 1, "ephemeral": False,
    }
    for field, value in (("active_turn_id", "ongoing"), ("pending_start_id", 1)):
        setattr(state, field, value)
        assert connector.read_owned_rollout(session, thread) is None
        setattr(state, field, None)
    connector._approval_requests["approval"] = {"pending": True, "session_id": session.session_id}
    assert connector.read_owned_rollout(session, thread) is None
    connector._approval_requests.clear()
    native["status"] = {"type": "active"}
    assert connector.read_owned_rollout(session, thread) is None
    assert all(call == ("thread/read", {"threadId": thread, "includeTurns": False}) for call in calls)
