import os
from pathlib import Path

import pytest

from nexus_connector_core import CoreError, LaunchIntent
from nexus_connector_core.discovery import candidate, candidate_pi_node_cli, discover_path
from nexus_connector_core.profiles import prepare_launch, verify_prepared


def fake_executable(tmp_path: Path, name: str) -> Path:
    path = tmp_path / (name + (".exe" if os.name == "nt" else ""))
    path.write_bytes(b"synthetic native binary")
    if os.name != "nt":
        path.chmod(0o755)
    return path


def test_discovery_never_trusts_cwd(tmp_path, monkeypatch):
    binary = fake_executable(tmp_path, "codex")
    monkeypatch.chdir(tmp_path)
    assert discover_path("codex_app_server", path_env=str(tmp_path)) == ()
    with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
        candidate("codex_app_server", binary)
    selected = candidate("codex_app_server", binary, explicit=True)
    assert selected.executable == str(binary.resolve())


def test_prepare_argv_unicode_and_binary_drift(tmp_path):
    binary = fake_executable(tmp_path, "pi")
    root = tmp_path / "projeto á com espaços"
    root.mkdir()
    selected = candidate("pi_rpc", binary, explicit=True)
    launch = prepare_launch(LaunchIntent("ag", "ws", "pi_rpc", model="modelo á"),
                            selected, root)
    assert launch.argv == (str(binary.resolve()), "--mode", "rpc", "--model", "modelo á")
    assert not launch.sandbox_applied
    verify_prepared(launch)
    binary.write_bytes(b"replaced executable")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        verify_prepared(launch)


def test_prepare_rejects_untrusted_candidate(tmp_path):
    binary = fake_executable(tmp_path, "codex")
    selected = candidate("codex_app_server", binary, explicit=True)
    with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
        prepare_launch(LaunchIntent("ag", "ws", "pi_rpc"), selected, tmp_path)


def test_explicit_pi_node_cli_binds_both_files_and_paths(tmp_path):
    node = fake_executable(tmp_path, "node")
    script = (tmp_path / "node_modules" / "@earendil-works" /
              "pi-coding-agent" / "dist" / "bundle" / "cli.js")
    script.parent.mkdir(parents=True)
    script.write_text("// pi cli\n", encoding="utf-8")
    with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
        candidate_pi_node_cli(node, script)
    selected = candidate_pi_node_cli(node, script, explicit=True)
    prepared = prepare_launch(LaunchIntent("ag", "ws", "pi_rpc"), selected, tmp_path)
    assert prepared.argv == (str(node.resolve()), str(script.resolve()), "--mode", "rpc")
    verify_prepared(prepared)
    script.write_text("// replaced pi cli\n", encoding="utf-8")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        verify_prepared(prepared)
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        prepare_launch(LaunchIntent("ag", "ws", "pi_rpc"), selected, tmp_path)
    refreshed = candidate_pi_node_cli(node, script, explicit=True)
    prepared = prepare_launch(LaunchIntent("ag", "ws", "pi_rpc"), refreshed, tmp_path)
    node.write_bytes(b"replaced node executable")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        verify_prepared(prepared)


def test_pi_node_cli_rejects_arbitrary_script(tmp_path):
    node = fake_executable(tmp_path, "node")
    script = tmp_path / "other.js"
    script.write_text("// arbitrary\n", encoding="utf-8")
    with pytest.raises(CoreError, match="NATIVE_VERSION_UNQUALIFIED"):
        candidate_pi_node_cli(node, script, explicit=True)
