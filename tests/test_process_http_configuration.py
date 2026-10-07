import asyncio
from dataclasses import replace
import json
import tomllib

import pytest

from nexus_connector_core import CoreError, InstallationCandidate, LaunchIntent, PreparedLaunch
from nexus_connector_core.environment import child_environment, ProcessHTTPEnvironment
from nexus_connector_core.harness_config import harness_http_template, process_http_arguments
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.native.adapter_types import HarnessSession, HarnessCapabilities
from test_native_runtime_bridge import context


def template(adapter):
    return harness_http_template(adapter,'https://nexus.test/mcp','mcp-cap:session',
        entry_name='nexus_session',harness_is_local=False,approved_origins={'https://nexus.test'},
        format_qualified=True)


def prepared(adapter, root=None):
    candidate=InstallationCandidate(adapter,'C:/native.exe','sha256:test','explicit','selected',version='technical')
    intent=LaunchIntent('agent','ws',adapter,auth_refs=('mcp-cap:session',))
    from nexus_connector_core.profiles import _root_fingerprint
    cwd = str(root) if root is not None else 'C:/workspace'
    identity = _root_fingerprint(root) if root is not None else 'root'
    return PreparedLaunch(intent,candidate,('C:/native.exe',),cwd,cwd,
                          identity,'profile',intent.auth_refs)


@pytest.mark.parametrize('inherit', [False, True])
@pytest.mark.parametrize('adapter',['codex_app_server','claude_stream'])
def test_factory_keeps_home_and_supplies_only_environment_reference_in_argv(adapter,tmp_path,monkeypatch,inherit):
    import nexus_connector_core.native.runtime_bridge as bridge
    item=template(adapter)
    launch=prepared(adapter, tmp_path)
    if inherit:
        from nexus_connector_core import HarnessSettings
        launch=replace(launch,intent=replace(launch.intent,harness_settings=HarnessSettings(inherit_global_mcps='enabled')))
    seen=[]
    class Resolver:
        async def resolve(self,ref):
            assert ref=='mcp-cap:session'
            return 'protected-session-material'
    class Native:
        def __init__(self,**options): seen.append(options)
        def start(self,*,owning_agent_id):
            return HarnessSession('native','codex',owning_agent_id,'STARTING',
                HarnessCapabilities(False,None,False,False,True),'2026-09-30T00:00:00Z')
        def close(self): pass
    monkeypatch.setattr(bridge,'qualified_build',lambda *a,**kw:True)
    monkeypatch.setattr(bridge,'load_adapter',lambda _:Native)
    async def run():
        environment=await child_environment(launch,Resolver(),provider_home=tmp_path,trusted_home=True,
                                            http_templates=(item,),process_http=True)
        assert isinstance(environment,ProcessHTTPEnvironment)
        assert environment['HOME']==str(tmp_path.resolve())
        assert 'protected-session-material' not in repr(environment)
        async def supply(_): return environment
        factory=CopiedAdapterFactory(supply)
        try:
            await factory.open(launch,'session',context(),stream_epoch='epoch')
        finally:
            factory.close()
    asyncio.run(run())
    options=seen[0]
    argv=options.get('command') or (options['binary'],*options['argv'])
    assert item.capability_ref not in repr(argv) and 'protected-session-material' not in repr(argv)
    assert options['env'][item.bearer_env_name]=='protected-session-material'
    if adapter=='codex_app_server':
        assert [p.name for p in tmp_path.iterdir()] == ['.codex']
        assert not list((tmp_path / '.codex').iterdir())
        assert options['env']['CODEX_HOME'] == str((tmp_path / '.codex').resolve())
        assert argv[-1].startswith('mcp_servers=')
        entry=tomllib.loads(argv[-1])['mcp_servers']['nexus_session']
        assert entry['bearer_token_env_var']==item.bearer_env_name
    else:
        assert not list(tmp_path.iterdir())
        assert ('--strict-mcp-config' in argv) is (not inherit)
        entry=json.loads(argv[-1])['mcpServers']['nexus_session']
        assert entry['headers']['Authorization']=='Bearer ${'+item.bearer_env_name+'}'
    assert entry['url']=='https://nexus.test/mcp'


@pytest.mark.parametrize('fault',['adapter','name','section','reference','environment','url','duplicate','empty'])
def test_process_configuration_refuses_invalid_or_unapproved_templates(fault):
    item=template('codex_app_server')
    changes={'adapter':{'adapter_id':'pi_rpc'},'name':{'entry_name':'name.inject'},
        'section':{'section':'other'},'reference':{'capability_ref':'mcp-cap:other'},
        'environment':{'bearer_env_name':'OPENAI_API_KEY'},'url':{'server_url':'http://remote.test/mcp'}}
    items=(replace(item,**changes[fault]),) if fault in changes else ((item,item) if fault=='duplicate' else ())
    with pytest.raises(CoreError):
        process_http_arguments('codex_app_server',items,('mcp-cap:session',))
