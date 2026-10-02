"""The public host discovery facade needs no runtime or provider process."""

from nexus_connector_core import discover_installations, get_runtime_catalog
from nexus_connector_core import CoreError, LaunchIntent, evaluate_runtime_availability
from nexus_connector_core.profiles import prepare_launch
import json
import os
import pytest

from tests.regression.test_c11_audit import _LAB_BINARY, _binary_name


def test_public_passive_discovery_preserves_full_candidate(tmp_path):
    binary = tmp_path / _binary_name("codex")
    binary.write_bytes(_LAB_BINARY)
    binary.chmod(0o755)
    inventory = discover_installations(
        adapter_ids=("codex_app_server",),
        trusted_roots=(tmp_path,), path_env=str(tmp_path),
    )
    assert len(inventory.candidates) == 1
    candidate = inventory.candidates[0]
    assert candidate.executable == str(binary.resolve())
    assert candidate.installation_ref.startswith("nexus-install-v1:")
    assert candidate.build_identity.startswith("sha256:")


def test_default_discovery_uses_core_catalog_without_runtime(tmp_path):
    assert any(item.adapter_id == "codex_app_server" and item.discoverable
               for item in get_runtime_catalog().runtimes)
    assert discover_installations(path_env=str(tmp_path)).candidates == ()


def test_visible_path_candidate_does_not_gain_launch_authority(tmp_path):
    binary = tmp_path / _binary_name('claude')
    binary.write_bytes(_LAB_BINARY)
    binary.chmod(0o755)
    observed, = discover_installations(adapter_ids=('claude_stream',), path_env=str(tmp_path)).candidates
    assert observed.executable == str(binary.resolve())
    assert observed.trust == 'untrusted' and observed.source == 'path'
    row, = [row for row in evaluate_runtime_availability([observed]).to_dict()['availability']
            if row['adapter_id'] == 'claude_stream']
    assert 'selection_required' in row['reasons']
    assert row['state'] not in ('NOT_INSTALLED', 'READY_FOR_RUNTIME')
    with pytest.raises(CoreError, match='BINDING_NOT_AUTHORIZED'):
        prepare_launch(LaunchIntent('agent', 'workspace', 'claude_stream'), observed, tmp_path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows package layouts')
@pytest.mark.parametrize('native_package_name', ['@openai/codex-win32-x64', '@openai/codex'])
def test_windows_npm_and_managed_pi_are_observed_without_running_shims(tmp_path, monkeypatch, native_package_name):
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Discovery executed a provider'))
    npm, pi_bin, node_dir = tmp_path / 'npm', tmp_path / 'agent' / 'bin', tmp_path / 'node'
    for directory in (npm, pi_bin, node_dir):
        directory.mkdir(parents=True)
    (npm / 'codex.cmd').write_text('DO NOT EXECUTE THIS WRAPPER')
    (pi_bin / 'pi-launcher.js').write_text('throw new Error("must never execute");')
    package = npm / 'node_modules' / '@openai' / 'codex'
    native_package = package / 'node_modules' / '@openai' / 'codex-win32-x64'
    binary = native_package / 'vendor' / 'x86_64-pc-windows-msvc' / 'bin' / 'codex.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(_LAB_BINARY)
    (package / 'package.json').write_text(json.dumps({'name': '@openai/codex'}))
    (native_package / 'package.json').write_text(json.dumps({'name': native_package_name}))
    install = pi_bin.parent / 'install'
    pi_package = install / 'releases' / '1.2.3' / 'node_modules' / '@earendil-works' / 'pi-coding-agent'
    script = pi_package / 'dist' / 'bundle' / 'cli.js'
    script.parent.mkdir(parents=True)
    script.write_text('throw new Error("must never execute");')
    (pi_package / 'package.json').write_text(json.dumps({'name': '@earendil-works/pi-coding-agent', 'version': '1.2.3'}))
    (install / 'current-version').write_text('1.2.3')
    node = node_dir / 'node.exe'
    node.write_bytes(_LAB_BINARY)
    path = os.pathsep.join(map(str, (npm, pi_bin, node_dir, npm)))
    candidates = discover_installations(path_env=path).candidates
    assert len(candidates) == 2
    codex = next(c for c in candidates if c.adapter_id == 'codex_app_server')
    pi = next(c for c in candidates if c.adapter_id == 'pi_rpc')
    assert codex.executable == str(binary.resolve())
    assert (pi.executable, pi.launch_script) == (str(node.resolve()), str(script.resolve()))
    assert all(c.trust == 'untrusted' for c in candidates)
    for item in candidates:
        with pytest.raises(CoreError, match='BINDING_NOT_AUTHORIZED'):
            prepare_launch(LaunchIntent('agent', 'workspace', item.adapter_id), item, tmp_path)
    selected = discover_installations(path_env=path, trusted_roots=(npm, install, node)).candidates
    assert all(c.trust == 'selected' for c in selected)
    (install / 'current-version').write_text('../1.2.3')
    assert not any(c.adapter_id == 'pi_rpc' for c in discover_installations(path_env=path).candidates)
