"""Known npm/managed POSIX layouts resolve physical targets without execution."""
import json
import os
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace

import pytest

from nexus_connector_core import CoreError, LaunchIntent, discover_installations
from nexus_connector_core.profiles import prepare_launch

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Real POSIX executable bits and symlinks')


def binary(path, *, platform='linux', arm=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = bytearray(64)
    if platform == 'darwin':
        data[:8] = b'\xcf\xfa\xed\xfe' + struct.pack('<I', 0x0100000C if arm else 0x01000007)
    else:
        data[:6] = b'\x7fELF\x02\x01'
        data[18:20] = struct.pack('<H', 183 if arm else 62)
    path.write_bytes(data)
    path.chmod(0o755)
    return path


def package(path, name):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'package.json').write_text(json.dumps({'name': name, 'version': '1.2.3'}))
    return path


def no_process(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Passive discovery started a process'))


@pytest.mark.parametrize('platform', ['linux', 'darwin'])
@pytest.mark.parametrize('arm', [False, True])
@pytest.mark.parametrize('placement', ['nested', 'hoisted', 'bundled'])
def test_npm_codex_symlink_resolves_native_payload(tmp_path, monkeypatch, platform, arm, placement):
    from nexus_connector_core import discovery_layouts
    monkeypatch.setattr(discovery_layouts, 'sys', SimpleNamespace(platform=platform), raising=False)
    no_process(monkeypatch)
    commands = tmp_path / 'prefix' / 'bin'
    commands.mkdir(parents=True)
    modules = commands.parent / 'lib/node_modules'
    root = package(modules / '@openai/codex', '@openai/codex')
    script = root / 'bin/codex.js'
    script.parent.mkdir()
    script.write_text('#!/usr/bin/env node\nthrow new Error("never execute");')
    script.chmod(0o755)
    (commands / 'codex').symlink_to(script)
    triple = ('aarch64' if arm else 'x86_64') + ('-apple-darwin' if platform == 'darwin' else '-unknown-linux-musl')
    name = '@openai/codex-' + platform + ('-arm64' if arm else '-x64')
    native_root = (root if placement == 'bundled' else
                   package((root / 'node_modules' if placement == 'nested' else modules) / name, '@openai/codex'))
    target = binary(native_root / 'vendor' / triple / 'bin/codex', platform=platform, arm=arm)
    found, = discover_installations(adapter_ids=('codex_app_server',), path_env=str(commands)).candidates
    assert found.executable == str(target.resolve()) and found.launch_script is None
    assert found.architecture == ('aarch64' if arm else 'x86_64')
    assert found.trust == 'untrusted' and found.version is None
    launcher_trusted, = discover_installations(adapter_ids=('codex_app_server',), path_env=str(commands),
                                              trusted_roots=(commands,)).candidates
    assert launcher_trusted.trust == 'untrusted'
    with pytest.raises(CoreError, match='BINDING_NOT_AUTHORIZED'):
        prepare_launch(LaunchIntent('agent', 'workspace', found.adapter_id), found, tmp_path)
    selected, = discover_installations(adapter_ids=('codex_app_server',), path_env=str(commands),
                                       trusted_roots=(native_root,)).candidates
    assert selected.trust == 'selected'


@pytest.mark.parametrize('managed', [False, True])
def test_pi_layout_preserves_distinct_node_pairs_and_explicit_overlap(tmp_path, monkeypatch, managed):
    no_process(monkeypatch)
    commands = tmp_path / 'agent/bin'
    commands.mkdir(parents=True)
    if managed:
        (commands / 'pi-launcher.js').write_text('throw new Error("never execute");')
        modules = commands.parent / 'install/releases/1.2.3/node_modules'
    else:
        modules = tmp_path / 'prefix/lib/node_modules'
    root = package(modules / '@earendil-works/pi-coding-agent', '@earendil-works/pi-coding-agent')
    script = root / 'dist/bundle/cli.js'
    script.parent.mkdir(parents=True)
    script.write_text('#!/usr/bin/env node\nthrow new Error("never execute");')
    script.chmod(0o755)
    if managed:
        (commands.parent / 'install/current-version').write_text('1.2.3')
        (commands / 'pi').write_text('#!/bin/sh\nexit 1\n')
        (commands / 'pi').chmod(0o755)
    else:
        (commands / 'pi').symlink_to(script)
    nodes = [binary(tmp_path / name / 'node') for name in ('node-a', 'node-b')]
    path = os.pathsep.join(map(str, [commands, *(node.parent for node in nodes), commands]))
    found = discover_installations(adapter_ids=('pi_rpc',), path_env=path).candidates
    assert {(item.executable, item.launch_script) for item in found} == {(str(node), str(script)) for node in nodes}
    assert all(item.trust == 'untrusted' for item in found)
    selected = discover_installations(adapter_ids=('pi_rpc',), path_env=path,
                                      trusted_roots=(root, *nodes)).candidates
    assert all(item.trust == 'selected' for item in selected)
    if managed:
        combined = discover_installations(adapter_ids=('pi_rpc',), path_env=path,
            trusted_roots=(root, *nodes), pi_install_root=commands.parent / 'install', pi_node=nodes[0])
        assert combined.candidates == selected


def test_unknown_executable_wrapper_is_not_interpreted(tmp_path, monkeypatch):
    no_process(monkeypatch)
    script = tmp_path / 'codex'
    script.write_text('#!/bin/sh\nexec /unrelated/private/codex "$@"\n')
    script.chmod(0o755)
    found, = discover_installations(adapter_ids=('codex_app_server',), path_env=str(tmp_path)).candidates
    assert found.executable == str(script) and found.architecture is None
    assert found.trust == 'untrusted'


@pytest.mark.parametrize('invalid', ['wrong-package', 'missing-payload', 'not-executable'])
def test_invalid_npm_layout_does_not_promote_or_erase_launcher(tmp_path, monkeypatch, invalid):
    no_process(monkeypatch)
    commands = tmp_path / 'bin'
    commands.mkdir()
    root = package(tmp_path / 'node_modules/@openai/codex',
                   '@unrelated/package' if invalid == 'wrong-package' else '@openai/codex')
    script = root / 'bin/codex.js'
    script.parent.mkdir()
    script.write_text('#!/usr/bin/env node\nthrow new Error("never execute");')
    script.chmod(0o755)
    (commands / 'codex').symlink_to(script)
    if invalid != 'missing-payload':
        target = binary(root / 'vendor/x86_64-unknown-linux-musl/bin/codex')
        if invalid == 'not-executable':
            target.chmod(0o644)
    found, = discover_installations(adapter_ids=('codex_app_server',), path_env=str(commands)).candidates
    assert found.executable == str(script) and found.architecture is None
    assert found.trust == 'untrusted'
