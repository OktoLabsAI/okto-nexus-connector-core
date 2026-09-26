import tomllib
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.config_document import (
    apply_toml_plan, plan_codex_toml_entry,
    plan_codex_toml_entry_removal,
)
from nexus_connector_core.config_persistence import apply_toml_plan_file
from nexus_connector_core.harness_config import harness_http_template


def _template(ref="mcp-cap:one", url="https://nexus.example.test/mcp"):
    return harness_http_template(
        "codex_app_server", url, ref, entry_name="okto-nexus",
        harness_is_local=False, approved_origins={"https://nexus.example.test"},
        format_qualified=True)


def test_add_preserves_third_party_bytes_and_uses_only_environment_reference():
    source = (b'# user comment\r\nmodel = "other"\r\n\r\n'
              b'[mcp_servers.third_party]\r\ncommand = "local"\r\n')
    template = _template()
    plan = plan_codex_toml_entry(source, template)
    result = apply_toml_plan(plan, source)
    assert result.startswith(source)
    assert b"[mcp_servers.okto-nexus]\r\nurl" in result
    parsed = tomllib.loads(result.decode())
    assert parsed["mcp_servers"]["third_party"] == {"command": "local"}
    assert parsed["mcp_servers"]["okto-nexus"] == template.entry()
    assert b"mcp-cap:one" not in result
    assert plan.changed_fields == ("bearer_token_env_var", "url")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_toml_plan(plan, source + b"# race\n")


def test_update_and_remove_require_exact_owned_predecessor():
    old = _template()
    source = (b'[mcp_servers.third_party]\ncommand = "local"\n\n' +
              b'[mcp_servers.okto-nexus]\n' +
              f'url = "{old.server_url}"\n'.encode() +
              f'bearer_token_env_var = "{old.bearer_env_name}"\n'.encode() +
              b'\n[features]\nflag = true\n')
    newer = _template("mcp-cap:two")
    with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
        plan_codex_toml_entry(source, newer)
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_codex_toml_entry(source, newer, previously_owned={"url": "wrong"})
    plan = plan_codex_toml_entry(source, newer, previously_owned=old.entry())
    changed = apply_toml_plan(plan, source)
    assert tomllib.loads(changed.decode())["mcp_servers"]["okto-nexus"] == newer.entry()
    assert b'[mcp_servers.third_party]\ncommand = "local"\n' in changed
    assert b'[features]\nflag = true\n' in changed
    assert not plan_codex_toml_entry(changed, newer,
                                    previously_owned=newer.entry()).changed
    removal = plan_codex_toml_entry_removal(
        changed, entry_name="okto-nexus", previously_owned=newer.entry())
    removed = apply_toml_plan(removal, changed)
    assert "okto-nexus" not in tomllib.loads(removed.decode())["mcp_servers"]
    assert b'[mcp_servers.third_party]\ncommand = "local"\n' in removed
    assert b'[features]\nflag = true\n' in removed


@pytest.mark.parametrize("source", [
    b'[mcp_servers.okto-nexus]\nurl = "x"\n',
    b'mcp_servers = {okto-nexus = {url = "x"}}\n',
])
def test_cannot_claim_existing_entry_without_owner(source):
    with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
        plan_codex_toml_entry(source, _template())


def test_complex_owned_table_and_invalid_toml_fail_closed():
    old = _template()
    source = (b'[mcp_servers.okto-nexus]\n' +
              f'url = "{old.server_url}"\n'.encode() +
              f'bearer_token_env_var = "{old.bearer_env_name}" # keep\n'.encode())
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_codex_toml_entry(source, _template("mcp-cap:two"),
                              previously_owned=old.entry())
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_codex_toml_entry(b'[broken\n', _template())
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        plan_codex_toml_entry(None, replace(old, entry_name="other]x"))


def test_file_apply_backups_and_rejects_stale_plan(tmp_path):
    path = tmp_path / "codex.toml"
    path.write_bytes(b'model = "other"\n')
    plan = plan_codex_toml_entry(path.read_bytes(), _template())
    result = apply_toml_plan_file(plan, path)
    assert result.changed and result.backup_path is not None
    assert result.backup_path.read_bytes() == b'model = "other"\n'
    assert tomllib.loads(path.read_text())["mcp_servers"]["okto-nexus"] == _template().entry()
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_toml_plan_file(plan, path)
