import asyncio
from dataclasses import replace
import json
import tomllib

import pytest

from nexus_connector_core import CoreError, HarnessSettings
from nexus_connector_core.environment import child_environment
from nexus_connector_core.harness_config import process_http_arguments
from test_process_http_configuration import prepared, template


class Resolver:
    async def resolve(self, reference):
        return 'private-mcp-value' if reference == 'vault:docs' else 'private-nexus-value'


def render(adapter, tmp_path, preset, *, inherit=False, approved=True):
    launch = prepared(adapter, tmp_path)
    refs = (*launch.secret_refs, 'vault:docs') if approved else launch.secret_refs
    launch = replace(launch, secret_refs=refs, intent=replace(launch.intent, mcp_preset=tuple(preset),
        harness_settings=HarnessSettings(inherit_global_mcps='enabled' if inherit else None)))
    environment = asyncio.run(child_environment(launch, Resolver(), provider_home=tmp_path, trusted_home=True,
        http_templates=(template(adapter),), process_http=True))
    argv = process_http_arguments(adapter, environment.http_templates, refs, inherit_global_mcps=inherit,
        disabled_mcp_names=environment.disabled_mcp_names, preset_entries=environment.preset_entries,
        preset_strict=environment.preset_strict)
    assert 'private-mcp-value' not in repr(argv)
    assert 'private-nexus-value' not in repr(argv)
    assert 'private-mcp-value' not in repr(environment)
    entries = (tomllib.loads(argv[-1])['mcp_servers'] if adapter == 'codex_app_server'
               else json.loads(argv[argv.index('--mcp-config') + 1])['mcpServers'])
    return entries, environment, argv


@pytest.mark.parametrize('adapter', ['codex_app_server', 'claude_stream'])
@pytest.mark.parametrize('transport', ['stdio', 'http'])
def test_native_presets_keep_secret_material_out_of_arguments(adapter, transport, tmp_path):
    entry = dict(name='docs', transport=transport)
    entry.update(dict(command='example', args=['serve'], env_refs={'DOCS_TOKEN': 'vault:docs'}) if transport == 'stdio'
                 else dict(url='https://example.test/mcp', header_refs={'Authorization': 'vault:docs'}))
    entries, env, _ = render(adapter, tmp_path, [entry])
    assert 'nexus_session' in entries and 'docs' in entries
    assert 'private-mcp-value' in list(env.values())
    if adapter == 'codex_app_server' and transport == 'stdio':
        assert entries['docs']['env_vars'] == ['DOCS_TOKEN']
        assert entries['docs']['env'] == {}


def test_unapproved_preset_secret_is_refused(tmp_path):
    with pytest.raises(CoreError) as caught:
        render('claude_stream', tmp_path, [dict(name='docs', transport='http', url='https://example.test/mcp',
               header_refs={'Authorization': 'vault:docs'})], approved=False)
    assert caught.value.code == 'BINDING_NOT_AUTHORIZED'


def test_codex_replacement_cannot_merge_old_transport_or_credentials(tmp_path):
    (tmp_path / 'config.toml').write_text('[mcp_servers.docs]\nurl="https://old.test/mcp"\nbearer_token_env_var="OLD_TOKEN"\n', encoding='utf-8')
    entries, _, _ = render('codex_app_server', tmp_path, [dict(name='docs', transport='stdio', command='example')], inherit=True)
    assert entries['docs'] == {'enabled': False}
    actual = next(v for k, v in entries.items() if k.startswith('okto_docs_'))
    assert actual['command'] == 'example'
    assert 'url' not in actual and 'bearer_token_env_var' not in actual


def test_claude_preserves_unrelated_global_mcp_and_disables_selected_entry(tmp_path):
    (tmp_path / '.claude.json').write_text(json.dumps({'mcpServers': {
        'keep': {'type': 'http', 'url': 'https://keep.test/mcp', 'headers': {'Authorization': 'global-private'}},
        'disabled': {'type': 'stdio', 'command': 'unused'}}}), encoding='utf-8')
    entries, env, argv = render('claude_stream', tmp_path,
        [dict(name='disabled', enabled=False, transport='stdio', command='unused')], inherit=True)
    assert set(entries) == {'keep', 'nexus_session'}
    assert '--strict-mcp-config' in argv
    assert 'global-private' not in repr(argv)
    assert 'global-private' in list(env.values())
    assert json.loads((tmp_path / '.claude.json').read_text())['mcpServers']['disabled']['command'] == 'unused'


def test_claude_native_arguments_use_private_file_and_cleanup_after_stop(tmp_path, monkeypatch):
    from pathlib import Path
    import nexus_connector_core.native.runtime_bridge as bridge
    from nexus_connector_core.native.adapter_types import HarnessSession, HarnessCapabilities
    from test_native_runtime_bridge import context
    (tmp_path / '.claude.json').write_text(json.dumps({'mcpServers': {'inherited': {
        'type': 'http', 'url': 'https://example.test/mcp', 'headersHelper': 'echo protected-helper'}}}), encoding='utf-8')
    launch = prepared('claude_stream', tmp_path)
    launch = replace(launch, intent=replace(launch.intent,
        harness_settings=HarnessSettings(inherit_global_mcps='enabled'),
        mcp_preset=({'name': 'extra', 'transport': 'stdio', 'command': 'example'},)))
    seen = []
    class Native:
        stopped = False
        def __init__(self, **options): seen.append(options)
        def start(self, *, owning_agent_id):
            return HarnessSession('native', 'claude_code', owning_agent_id, 'STARTING',
                HarnessCapabilities(False, None, False, False, True), '2026-10-09T00:00:00Z')
        def send(self, *args): pass
        def close(self): self.stopped = True; return 'graceful'
        def observe_lifecycle(self, session): return {'stop_observed': self.stopped}
    monkeypatch.setattr(bridge, 'qualified_build', lambda *a, **kw: True)
    monkeypatch.setattr(bridge, 'load_adapter', lambda _: Native)
    async def run():
        async def supply(_):
            return await child_environment(launch, Resolver(), provider_home=tmp_path, trusted_home=True,
                http_templates=(template('claude_stream'),), process_http=True)
        factory = bridge.CopiedAdapterFactory(supply)
        try:
            session = await factory.open(launch, 'session', context(), stream_epoch='epoch')
            args = seen[0]['argv']
            assert 'protected-helper' not in repr(args)
            config = Path(args[args.index('--mcp-config') + 1])
            assert json.loads(config.read_text())['mcpServers']['inherited']['headersHelper'] == 'echo protected-helper'
            await session.close()
            assert not config.exists() and not config.parent.exists()
        finally:
            factory.close()
    asyncio.run(run())
