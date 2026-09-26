import json
import threading

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.config_document import plan_json_entry, plan_json_entry_removal
from nexus_connector_core.config_persistence import _file_lock, apply_json_plan_file


def _plan(source):
    return plan_json_entry(source, section="mcpServers", entry_name="okto-nexus",
                           proposed={"type": "http", "url": "https://nexus.test/mcp"})


def test_create_and_update_preserve_source_backup_and_other_entries(tmp_path):
    path = tmp_path / "harness.json"
    first = _plan(None)
    created = apply_json_plan_file(first, path)
    assert created.changed and created.backup_path is None
    initial = path.read_bytes()
    assert json.loads(initial)["mcpServers"]["okto-nexus"]["type"] == "http"
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_json_plan_file(first, path)

    owned = {"type": "http", "url": "https://nexus.test/mcp"}
    external = json.dumps({"mcpServers": {"okto-nexus": owned,
                                          "third-party": {"command": "other"}}}).encode()
    path.write_bytes(external)
    second = plan_json_entry(external, section="mcpServers", entry_name="okto-nexus",
                             previously_owned=owned,
                             proposed={"type": "http", "url": "https://new.test/mcp"})
    updated = apply_json_plan_file(second, path)
    assert updated.changed and updated.backup_path is not None
    assert updated.backup_path.read_bytes() == external
    final = json.loads(path.read_bytes())
    assert final["mcpServers"]["third-party"] == {"command": "other"}
    assert final["mcpServers"]["okto-nexus"]["url"] == "https://new.test/mcp"


def test_conflicting_edit_never_replaced_or_backed_up(tmp_path):
    path = tmp_path / "harness.json"
    original = b'{"other":1}'
    plan = _plan(original)
    path.write_bytes(b'{"other":2}')
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_json_plan_file(plan, path)
    assert path.read_bytes() == b'{"other":2}'
    assert list(tmp_path.glob("*.bak")) == []


def test_idempotent_plan_checks_revision_without_backup(tmp_path):
    path = tmp_path / "harness.json"
    source = b'{"mcpServers":{"okto-nexus":{"type":"http"}}}'
    path.write_bytes(source)
    owned = {"type": "http"}
    plan = plan_json_entry(source, section="mcpServers", entry_name="okto-nexus",
                           previously_owned=owned, proposed=owned)
    result = apply_json_plan_file(plan, path)
    assert not result.changed and result.backup_path is None
    assert path.read_bytes() == source
    assert list(tmp_path.glob("*.bak")) == []
    path.write_bytes(source + b" ")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_json_plan_file(plan, path)


def test_noncooperating_edit_during_apply_detected_before_replace(tmp_path, monkeypatch):
    from nexus_connector_core import config_persistence

    path = tmp_path / "harness.json"
    original = b'{"other":1}'
    path.write_bytes(original)
    plan = _plan(original)
    write_new = config_persistence._write_new

    def edit_after_temp(target, data, *, mode=0o600):
        write_new(target, data, mode=mode)
        if target.suffix == ".tmp":
            path.write_bytes(b'{"external":true}')

    monkeypatch.setattr(config_persistence, "_write_new", edit_after_temp)
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_json_plan_file(plan, path)
    assert path.read_bytes() == b'{"external":true}'
    assert not list(tmp_path.glob("*.tmp"))


def test_adjacent_lock_serializes_and_times_out(tmp_path):
    path = tmp_path / "harness.json"
    lock = path.with_name(path.name + ".lock")
    held = threading.Event()
    release = threading.Event()

    def holder():
        with _file_lock(lock, 1):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(2)
        with pytest.raises(CoreError, match="CONFIG_LOCK_BUSY"):
            apply_json_plan_file(_plan(None), path, lock_timeout_seconds=0.05)
        assert not path.exists()
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert apply_json_plan_file(_plan(None), path).changed


def test_symlink_target_refused(tmp_path):
    target = tmp_path / "actual.json"
    target.write_bytes(b'{"other":1}')
    link = tmp_path / "harness.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_json_plan_file(_plan(target.read_bytes()), link)
    assert target.read_bytes() == b'{"other":1}'


def test_symlink_lock_refused(tmp_path):
    path = tmp_path / "harness.json"
    target = tmp_path / "other.lock"
    target.write_bytes(b"sentinel")
    lock = path.with_name(path.name + ".lock")
    try:
        lock.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_json_plan_file(_plan(None), path)
    assert target.read_bytes() == b"sentinel"
    assert not path.exists()


def test_post_replace_sync_failure_reports_possible_effect(tmp_path, monkeypatch):
    from nexus_connector_core import config_persistence

    path = tmp_path / "harness.json"

    def fail_sync(_parent):
        raise OSError("simulated directory sync failure")

    monkeypatch.setattr(config_persistence, "_sync_directory", fail_sync)
    with pytest.raises(CoreError, match="OUTCOME_UNKNOWN") as exc:
        apply_json_plan_file(_plan(None), path)
    assert exc.value.possible_effect
    assert json.loads(path.read_bytes())["mcpServers"]["okto-nexus"]["type"] == "http"


def test_owned_removal_uses_same_backup_and_cas(tmp_path):
    path = tmp_path / "harness.json"
    owned = {"type": "http"}
    source = json.dumps({"mcpServers": {"okto-nexus": owned,
                                        "third-party": {"command": "other"}}}).encode()
    path.write_bytes(source)
    plan = plan_json_entry_removal(source, section="mcpServers",
                                   entry_name="okto-nexus", previously_owned=owned)
    result = apply_json_plan_file(plan, path)
    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == source
    assert json.loads(path.read_bytes()) == {
        "mcpServers": {"third-party": {"command": "other"}}}
