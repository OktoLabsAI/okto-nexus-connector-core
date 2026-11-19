"""The retained source must have the same dialogue before and after normal close."""

import hashlib
import json
import re
from uuid import uuid4

import pytest

from nexus_connector_core.native.claude_saved_history import observe_claude_saved_history


def _record(**fields):
    return json.dumps(fields, ensure_ascii=True).encode() + b"\n"


def _usage(session_uuid):
    return _record(type="cost-state", sessionId=session_uuid, totalCostUSD=0.1, totalAPIDuration=1,
                   totalAPIDurationWithoutRetries=1, totalToolDuration=0, totalLinesAdded=0,
                   totalLinesRemoved=0, totalDuration=2, startTime=1, modelUsage={}, hasUnknownModelCost=False)


@pytest.fixture
def saved(tmp_path):
    home, workspace = tmp_path / "profile", tmp_path / "demo"
    workspace.mkdir()
    session_uuid = str(uuid4())
    directory = re.sub(r"[^A-Za-z0-9]", "-", str(workspace))
    path = home / "projects" / directory / f"{session_uuid}.jsonl"
    path.parent.mkdir(parents=True)
    contents = b"".join(_record(type=kind, sessionId=session_uuid, cwd=str(workspace), isSidechain=False,
                               message={"role": kind, "content": "private history"})
                        for kind in ("user", "assistant"))
    path.write_bytes(contents)
    return str(home), session_uuid, str(workspace), path, contents


def test_same_history_and_normal_close_metadata_can_both_be_proved(saved):
    home, session_uuid, cwd, path, contents = saved
    prior = observe_claude_saved_history(home, session_uuid, cwd)
    assert prior.sha256 == hashlib.sha256(contents).hexdigest()
    assert prior == observe_claude_saved_history(home, session_uuid, cwd, before_close=prior)
    assert all(value not in repr(prior) for value in (home, session_uuid, cwd, "private history"))
    with path.open("ab") as data:
        data.write(_usage(session_uuid))
    closed = observe_claude_saved_history(home, session_uuid, cwd, before_close=prior)
    assert closed.file_identity == prior.file_identity
    assert closed.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert closed == observe_claude_saved_history(home, session_uuid, cwd)


@pytest.mark.parametrize("change", ["modified-prefix", "different-inode", "new-turn", "foreign-cost", "unfinished"])
def test_a_different_saved_history_cannot_be_verified_after_close(saved, change):
    home, session_uuid, cwd, path, contents = saved
    prior = observe_claude_saved_history(home, session_uuid, cwd)
    if change == "different-inode":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(contents)
        replacement.replace(path)
    elif change == "modified-prefix":
        path.write_bytes(contents.replace(b"private", b"changed") + _usage(session_uuid))
    else:
        appended = {
            "new-turn": _record(type="user", sessionId=session_uuid, cwd=cwd, isSidechain=False),
            "foreign-cost": _usage(str(uuid4())),
            "unfinished": _usage(session_uuid)[:-1],
        }
        with path.open("ab") as data:
            data.write(appended[change])
    assert observe_claude_saved_history(home, session_uuid, cwd, before_close=prior) is None


def test_directory_name_does_not_authorize_a_different_workspace(saved):
    home, session_uuid, cwd, path, contents = saved
    first, second = (json.loads(line) for line in contents.splitlines())
    second["cwd"] += "-foreign"
    path.write_bytes(_record(**first) + _record(**second))
    assert observe_claude_saved_history(home, session_uuid, cwd) is None
