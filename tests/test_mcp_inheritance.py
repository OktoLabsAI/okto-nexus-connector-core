import asyncio
from dataclasses import replace
import json

import pytest

from nexus_connector_core import CoreError, HarnessSettings, validate_harness_settings
from nexus_connector_core.environment import child_environment
from test_process_http_configuration import prepared, template


class Resolver:
    async def resolve(self, reference):
        return 'session-material'


@pytest.mark.parametrize('adapter', ['codex_app_server', 'claude_stream'])
def test_only_declared_global_credentials_are_forwarded_without_mutating_files(tmp_path, monkeypatch, adapter):
    launch = prepared(adapter, tmp_path)
    launch = replace(launch, intent=replace(launch.intent,
        harness_settings=HarnessSettings(inherit_global_mcps='enabled')))
    if adapter == 'codex_app_server':
        path = tmp_path / 'config.toml'
        content = '[mcp_servers.external]\nurl="http://127.0.0.1:1/mcp"\nbearer_token_env_var="EXTERNAL_TOKEN"\nenv_vars=["NEXUS_OPERATOR_KEY", "OTHER_PRIVILEGED"]\n'
    else:
        path = tmp_path / '.claude.json'
        content = json.dumps({'mcpServers': {'external': {'type':'http', 'url':'http://127.0.0.1:1/mcp',
            'headers': {'Authorization':'Bearer ${EXTERNAL_TOKEN}', 'Bad':'${NEXUS_OPERATOR_KEY}', 'AlsoBad':'${OTHER_PRIVILEGED}'}}}})
    path.write_text(content)
    monkeypatch.setenv('EXTERNAL_TOKEN', 'host-secret')
    monkeypatch.setenv('UNRELATED_TOKEN', 'unrelated-secret')
    monkeypatch.setenv('NEXUS_OPERATOR_KEY', 'operator-secret')
    monkeypatch.setenv('OTHER_PRIVILEGED', 'nxc4_privileged')
    async def run():
        env = await child_environment(launch, Resolver(), provider_home=tmp_path, trusted_home=True,
            http_templates=(template(adapter),), process_http=True)
        assert env['EXTERNAL_TOKEN'] == 'host-secret'
        assert not {'UNRELATED_TOKEN','NEXUS_OPERATOR_KEY','OTHER_PRIVILEGED'} & set(env)
        assert 'host-secret' not in repr(env)
        disabled = replace(launch,intent=replace(launch.intent,harness_settings=HarnessSettings()))
        env = await child_environment(disabled, Resolver(), provider_home=tmp_path, trusted_home=True,
            http_templates=(template(adapter),), process_http=True)
        assert 'EXTERNAL_TOKEN' not in env
    asyncio.run(run())
    assert path.read_text() == content


def test_inheritance_requires_approved_home_and_cannot_bypass_process_configuration(tmp_path):
    launch = prepared('codex_app_server', tmp_path)
    launch = replace(launch,intent=replace(launch.intent,harness_settings=HarnessSettings(inherit_global_mcps='enabled')))
    async def run():
        for options in ({}, {'provider_home':tmp_path}, {'provider_home':tmp_path,'trusted_home':True,
                'http_templates':(template('codex_app_server'),)}):
            with pytest.raises(CoreError):
                await child_environment(launch, Resolver(), **options)
    asyncio.run(run())


def test_pi_cannot_claim_native_mcp_support():
    with pytest.raises(CoreError):
        validate_harness_settings('pi_rpc', {'inherit_global_mcps':'enabled'})


def test_broken_global_config_is_scoped_and_does_not_expose_contents(tmp_path):
    from nexus_connector_core.mcp_inheritance import global_mcp_environment
    (tmp_path/'config.toml').write_text('host-secret invalid toml')
    with pytest.raises(CoreError) as error:
        global_mcp_environment('codex_app_server', {'CODEX_HOME':str(tmp_path)})
    assert 'host-secret' not in str(error.value)
