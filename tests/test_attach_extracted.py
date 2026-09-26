import os
import json

import pytest

from nexus_connector_core.native.adapter_types import ErrorCode, NativeAdapterError
from nexus_connector_core.native.adapters.claude_code_attach import (
    ClaudeCodeAttachConnector,
    discover_attachable_sessions,
)


@pytest.mark.skipif(os.name != "nt", reason="Windows unsupported-platform contract")
def test_attach_remains_explicit_and_unsupported_on_windows(tmp_path):
    connector = ClaudeCodeAttachConnector(12345, sessions_dir=tmp_path, env={})
    result = connector.probe()
    assert not result.ok
    assert result.reason == "platform_unsupported"
    assert result.category == "unsupported_platform"
    with pytest.raises(NativeAdapterError):
        discover_attachable_sessions(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="Claude attach uses POSIX checks")
def test_discovery_and_probe_reject_registry_pid_mismatch(tmp_path):
    (tmp_path / "123.json").write_text(
        json.dumps({"pid": 456, "kind": "interactive"}), encoding="utf-8")
    (tmp_path / "789.json").write_text(
        json.dumps({"pid": True, "kind": "interactive"}), encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "999.json").write_text(
        json.dumps({"pid": 999, "kind": "interactive"}), encoding="utf-8")
    (tmp_path / "999.json").symlink_to(tmp_path / "other" / "999.json")
    assert discover_attachable_sessions(tmp_path) == []

    connector = ClaudeCodeAttachConnector(123, sessions_dir=tmp_path)
    result = connector.probe()
    assert not result.ok
    assert result.reason == "registry_pid_mismatch"
    assert result.category == "protocol_drift"
    with pytest.raises(NativeAdapterError) as failure:
        connector.start(owning_agent_id="agent")
    assert failure.value.details["not_sent"] is True


@pytest.mark.parametrize("target_pid", [0, -1, True, "123"])
def test_attach_target_must_be_a_positive_integer(target_pid, tmp_path):
    with pytest.raises(ValueError):
        ClaudeCodeAttachConnector(target_pid, sessions_dir=tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="Claude attach uses POSIX checks")
def test_pid_reuse_guard_fails_closed_when_key_directory_cannot_be_listed(tmp_path):
    class UnreadableDir:
        def glob(self, _pattern):
            raise PermissionError("key directory denied")

    connector = ClaudeCodeAttachConnector(os.getpid(), sessions_dir=tmp_path)
    connector._key_path = tmp_path / f"{os.getpid()}.deadbeef.key"
    connector._sessions_dir = UnreadableDir()
    with pytest.raises(NativeAdapterError) as failure:
        connector._check_no_pid_reuse()
    assert failure.value.details["reason"] == "key_directory_unreadable"
    assert failure.value.details["not_sent"] is True


@pytest.mark.skipif(os.name == "nt", reason="Claude attach uses POSIX checks")
def test_pid_reuse_guard_does_not_ignore_unreadable_current_key(tmp_path, monkeypatch):
    pid = os.getpid()
    key = tmp_path / f"{pid}.deadbeef.key"
    key.write_text("{}", encoding="utf-8")
    connector = ClaudeCodeAttachConnector(pid, sessions_dir=tmp_path)
    connector._key_path = key
    connector._proc_start = "original"

    def unreadable(_path):
        raise NativeAdapterError(ErrorCode.NOT_FOUND, "key unreadable", {})

    monkeypatch.setattr(connector, "_read_key", unreadable)
    with pytest.raises(NativeAdapterError, match="key unreadable"):
        connector._check_no_pid_reuse()


@pytest.mark.skipif(os.name == "nt", reason="Claude attach uses POSIX checks")
def test_pid_reuse_guard_rejects_disappearing_proc_start(tmp_path, monkeypatch):
    pid = os.getpid()
    key = tmp_path / f"{pid}.deadbeef.key"
    key.write_text("{}", encoding="utf-8")
    connector = ClaudeCodeAttachConnector(pid, sessions_dir=tmp_path)
    connector._key_path = key
    connector._proc_start = "original"
    monkeypatch.setattr(connector, "_read_key", lambda _path: {"peerToken": "token"})
    with pytest.raises(NativeAdapterError) as failure:
        connector._check_no_pid_reuse()
    assert failure.value.details["reason"] == "pid_reuse_guard_tripped"
    assert failure.value.details["not_sent"] is True
