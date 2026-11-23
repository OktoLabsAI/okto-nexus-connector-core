import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexus_connector_core.native.adapter_types import HarnessSession
from nexus_connector_core.native.adapters.pi import PiRpcConnector
from nexus_connector_core.native.pi_saved_history import observe_pi_saved_history, pi_saved_history_current


@pytest.fixture
def saved_file(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    home = tmp_path / "profile"
    encoded = re.sub(r"[/\\:]", "-", str(root).lstrip("/\\"))
    session = "hsess_" + "a" * 32
    file = home / "sessions" / f"--{encoded}--" / f"2026-11-23T12-30-00-000Z_{session}.jsonl"
    file.parent.mkdir(parents=True)
    entries = [
        {"type": "session", "version": 3, "id": session, "cwd": str(root)},
        {"type": "message", "id": "aaaaaaaa", "parentId": None, "message": {"role": "user", "content": "private"}},
        {"type": "message", "id": "bbbbbbbb", "parentId": "aaaaaaaa",
         "message": {"role": "assistant", "stopReason": "stop", "content": "private"}},
    ]

    def write():
        file.write_bytes(b"".join(json.dumps(entry).encode() + b"\n" for entry in entries))
    write()
    return SimpleNamespace(attach=(str(home), str(root), str(file), session, "bbbbbbbb", 2),
                           file=file, entries=entries, write=write)


def test_pi_proof_rechecks_bytes_leaf_and_private_profile(saved_file):
    evidence = observe_pi_saved_history(*saved_file.attach)
    assert evidence is not None and pi_saved_history_current(evidence)
    assert "private" not in repr(evidence) and str(saved_file.file) not in repr(evidence)
    with saved_file.file.open("r+b") as handle:
        original = handle.read()
        handle.seek(0)
        handle.write(original.replace(b'"private"', b'"changed"', 1))
    assert not pi_saved_history_current(evidence)
    assert observe_pi_saved_history(*saved_file.attach) is not None
    outside = saved_file.file.parent.parent / saved_file.file.name
    outside.write_bytes(original)
    home, cwd, _, native, leaf, count = saved_file.attach
    assert observe_pi_saved_history(home, cwd, str(outside), native, leaf, count) is None


def test_pi_proof_accepts_stable_handle_and_path_timestamp_precision(saved_file, monkeypatch):
    fstat = os.fstat

    def handle_stat(fd):
        status = fstat(fd)
        fields = {name: getattr(status, name) for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns")}
        return SimpleNamespace(**fields, st_ctime_ns=status.st_ctime_ns + 1000)

    monkeypatch.setattr(os, "fstat", handle_stat)
    assert observe_pi_saved_history(*saved_file.attach) is not None


@pytest.mark.parametrize("change", ["wrong_cwd", "wrong_id", "fork", "unfinished", "truncated",
                                    "unknown_parent", "another_leaf", "old_schema"])
def test_pi_proof_refuses_history_that_cannot_restore_the_owned_branch(saved_file, change):
    header, _, answer = saved_file.entries
    changes = {
        "wrong_cwd": lambda: header.update(cwd=Path(header["cwd"]).parent.as_posix()),
        "wrong_id": lambda: header.update(id="hsess_" + "b" * 32),
        "fork": lambda: header.update(parentSession="elsewhere"),
        "unfinished": lambda: answer["message"].update(stopReason="aborted"),
        "truncated": lambda: saved_file.entries.pop(),
        "unknown_parent": lambda: answer.update(parentId="cccccccc"),
        "another_leaf": lambda: answer.update(id="dddddddd"),
        "old_schema": lambda: header.update(version=2),
    }
    changes[change]()
    saved_file.write()
    assert observe_pi_saved_history(*saved_file.attach) is None


def test_hosted_pi_history_checks_exact_owner_again_after_file_read(saved_file):
    home, cwd, file, session_id, leaf, entries = saved_file.attach
    connector = PiRpcConnector(cwd=cwd, env={"PI_CODING_AGENT_DIR": home}, hosted_rpc=Path("reviewed-host.js"))
    session = HarnessSession(session_id, "pi", "agent", "RUNNING", connector.capabilities, "start")
    transport = Mock(_hosted_rpc_revision=2, _response_ids_required=True)
    transport.is_alive.return_value = True
    connector._transport = transport
    connector._session_id = session_id
    expected = observe_pi_saved_history(*saved_file.attach)
    assert expected is not None
    idle = {"sessionId": session_id, "sessionFile": file, "leaf": leaf, "entries": entries, "sha256": expected.sha256}
    transport.request.return_value = {"success": True, "data": idle}
    assert connector.read_current_owned_saved_history(session) == expected
    assert transport.request.call_count == 2

    transport.request.return_value = {"success": True, "data": idle | {"sha256": "b" * 64}}
    assert connector.read_current_owned_saved_history(session) is None
    refused = {"success": False, "data": None}
    transport.request.side_effect = [{"success": True, "data": idle}, refused]
    assert connector.read_current_owned_saved_history(session) is None
    transport.request.side_effect = [{"success": True, "data": idle | {"sessionId": "other"}}]
    assert connector.read_current_owned_saved_history(session) is None
    transport.request.side_effect = None
    transport._hosted_rpc_revision = 1
    transport.request.reset_mock()
    assert connector.read_current_owned_saved_history(session) is None
    transport.request.assert_not_called()
