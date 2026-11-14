"""Authentication observation precedes any thread/turn; peers are synthetic."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

from nexus_connector_core import OperationKey, SessionKey
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate, LaunchIntent, OpenOperation, ShutdownPolicy
from nexus_connector_core.native.adapter_types import NativeAdapterError
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.runtime import LocalRuntimeCore
from test_native_runtime_bridge import context
from test_codex_handshake import _codex_schema, _validates


def peer(tmp_path, response):
    path = tmp_path / 'auth_peer.py'
    path.write_text('import json,sys\n'
        f'response={response!r}\n'
        'for line in sys.stdin:\n'
        ' request=json.loads(line); method=request.get("method")\n'
        ' with open("methods.jsonl","a") as output: output.write(json.dumps(request)+"\\n")\n'
        ' if method=="initialize":\n'
        '  value={"result":{"userAgent":"okto-nexus/0.157.0"}}\n'
        ' elif method=="account/read":\n'
        '  if response is None: continue\n'
        '  value=response\n'
        ' elif method in ("thread/start","thread/resume"):\n'
        '  value={"result":{"thread":{"id":"synthetic-thread","status":{"type":"idle"}}}}\n'
        ' elif method=="initialized": continue\n'
        ' else: value={"result":{}}\n'
        ' print(json.dumps({"id":request["id"],**value}),flush=True)\n',encoding='utf-8')
    return path


def messages(tmp_path):
    return [json.loads(line) for line in (tmp_path/'methods.jsonl').read_text().splitlines()]


@pytest.mark.parametrize('observation', [
    {'requiresOpenaiAuth':False,'account':None},
    {'requiresOpenaiAuth':False},
    {'requiresOpenaiAuth':True,'account':{'type':'apiKey'}},
    {'requiresOpenaiAuth':True,'account':{'type':'chatgpt','email':'PRIVATE@example.invalid','planType':'plus'}},
    {'requiresOpenaiAuth':True,'account':{'type':'amazonBedrock'}},
])
def test_authenticated_and_custom_provider_observations_allow_thread_without_account_metadata(tmp_path, observation):
    _validates(_codex_schema(),'GetAccountResponse',observation)
    script=peer(tmp_path,{'result':observation})
    connector=CodexAppServerConnector(command=[sys.executable,str(script)],cwd=str(tmp_path),env={},handshake_timeout_s=2)
    try:
        session=connector.start(owning_agent_id='agent')
        observed=messages(tmp_path)
        assert [m['method'] for m in observed]==['initialize','initialized','account/read','thread/start']
        assert observed[2]['params']=={'refreshToken':False}
        assert 'PRIVATE' not in json.dumps(session.metadata)
        assert 'account' not in session.metadata and 'account' not in session.compatibility_report
    finally:
        assert connector.close() in ('graceful','forced','already_closed')


@pytest.mark.parametrize('response,reason', [
    ({'result':{'requiresOpenaiAuth':True,'account':None}},'provider_auth_required'),
    ({'result':{'requiresOpenaiAuth':True}},'protocol_incompatible'),
    ({'result':{'requiresOpenaiAuth':'true','account':None}},'protocol_incompatible'),
    ({'result':{'account':None}},'protocol_incompatible'),
    ({'result':{'requiresOpenaiAuth':True,'account':{'type':'unknown'}}},'protocol_incompatible'),
    ({'error':{'code':-32601,'message':'PRIVATE_ACCOUNT_TOKEN'}},'protocol_incompatible'),
    ({'error':{'code':401,'message':'PRIVATE_ACCOUNT_TOKEN'}},'provider_auth_observation_unconfirmed'),
    (None,'provider_auth_observation_unconfirmed'),
])
def test_absent_unknown_or_unsupported_auth_never_starts_thread_and_keeps_no_private_detail(tmp_path,monkeypatch,response,reason):
    from nexus_connector_core.native.adapters import codex
    created=[];original=codex._CodexTransport.start
    def capture(transport):
        original(transport);created.append(transport)
    monkeypatch.setattr(codex._CodexTransport,'start',capture)
    script=peer(tmp_path,response)
    connector=CodexAppServerConnector(command=[sys.executable,str(script)],cwd=str(tmp_path),env={},handshake_timeout_s=.3)
    with pytest.raises(NativeAdapterError) as caught:
        connector.start(owning_agent_id='agent')
    assert caught.value.details=={'reason':reason}
    assert 'PRIVATE' not in str(caught.value)
    assert [m['method'] for m in messages(tmp_path)]==['initialize','initialized','account/read']
    assert len(created)==1 and created[0]._proc.poll() is not None
    assert connector.close() in ('graceful','forced','already_closed')
    assert connector._closed_event.is_set() and connector._transport is None


@pytest.mark.parametrize('response,expected',[
    ({'result':{'requiresOpenaiAuth':True,'account':None}},'PROVIDER_AUTH_REQUIRED'),
    ({'result':{}},'NATIVE_PROTOCOL_INCOMPATIBLE'),
    ({'error':{'code':-32601,'message':'PRIVATE'}},'NATIVE_PROTOCOL_INCOMPATIBLE'),
    ({'error':{'code':401,'message':'PRIVATE'}},'NATIVE_STARTUP_FAILED'),
])
def test_runtime_keeps_contained_open_failure_durable_without_turn_or_automatic_retry(tmp_path,monkeypatch,response,expected):
    import nexus_connector_core.native.runtime_bridge as bridge
    import nexus_connector_core.native.adapters.codex as codex
    script=peer(tmp_path,response)
    actual=codex.CodexAppServerConnector
    created=[]
    class SyntheticCodex(actual):
        def __init__(self, **kwargs):
            kwargs.update(command=[sys.executable,str(script)],env={},handshake_timeout_s=2)
            super().__init__(**kwargs);created.append(self)
    monkeypatch.setattr(codex,'CodexAppServerConnector',SyntheticCodex)
    monkeypatch.setattr(bridge,'qualified_build',lambda *a,**kw:True)
    async def run():
        selected=InstallationCandidate('codex_app_server',sys.executable,fingerprint(Path(sys.executable)),
            'explicit','selected',version='synthetic')
        journal=SQLiteJournal(tmp_path/'journal.db')
        async def environment(_):return {}
        runtime=LocalRuntimeCore(journal,CopiedAdapterFactory(environment),
            candidates={'codex_app_server':selected},workspace_roots={'ws':str(tmp_path)})
        try:
            prepared=await runtime.prepare(LaunchIntent('agent','ws','codex_app_server'),context())
            operation=OpenOperation('open','session','epoch',prepared)
            receipt=await runtime.open(operation,context())
            assert receipt.stage=='FAILED' and receipt.error_code==expected
            assert receipt.possible_effect is True and receipt.retry_safe is False
            assert await journal.get_receipt(OperationKey('srv','exe','open'))==receipt
            assert await journal.get_receipt(OperationKey('srv','exe','turn')) is None
            assert (await runtime.observe_process_birth(SessionKey('srv','exe','session'))).state in {'NOT_RUNNING','NOT_OBSERVED'}
            assert await runtime.open(operation,context())==receipt
            assert len(created)==1
            assert [m['method'] for m in messages(tmp_path)]==['initialize','initialized','account/read']
        finally:
            await runtime.shutdown(ShutdownPolicy(1,1));journal.close()
    asyncio.run(run())


def test_unknown_cleanup_does_not_claim_a_contained_authentication_failure(tmp_path,monkeypatch):
    import nexus_connector_core.native.runtime_bridge as bridge
    from nexus_connector_core.native.adapter_types import ErrorCode
    from nexus_connector_core.models import PreparedLaunch
    from nexus_connector_core.profiles import _root_fingerprint
    class UnknownCleanup:
        def __init__(self, **kwargs):pass
        def start(self, **kwargs):
            raise NativeAdapterError(ErrorCode.PERMISSION_DENIED,'Authentication unavailable',
                {'reason':'provider_auth_required'})
        def close(self):return 'unknown'
    monkeypatch.setattr(bridge,'load_adapter',lambda _:UnknownCleanup)
    monkeypatch.setattr(bridge,'qualified_build',lambda *a,**kw:True)
    selected=InstallationCandidate('codex_app_server',sys.executable,fingerprint(Path(sys.executable)),
        'explicit','selected',version='synthetic')
    prepared=PreparedLaunch(LaunchIntent('agent','ws','codex_app_server'),selected,(sys.executable,),
        str(tmp_path),str(tmp_path),_root_fingerprint(tmp_path),'profile',())
    async def run():
        async def environment(_):return {}
        factory=CopiedAdapterFactory(environment)
        try:
            with pytest.raises(NativeAdapterError):
                await factory.open(prepared,'session',context(),stream_epoch='epoch')
        finally:factory.close()
    asyncio.run(run())


@pytest.mark.parametrize('overrides,resume,required',[
    ({'modelProvider':'approved-custom'},None,True),
    ({'modelProvider':'openai'},None,True),
    ({'config':{'model_provider':'approved-custom'}},None,True),
    ({'config':{'model_providers.custom.requires_openai_auth':False}},None,True),
    ({'config':{'profile':'approved-custom'}},None,True),
    ({'cwd':'C:/approved-other-project'},None,True),
    ({},'synthetic-thread',True),
    ({},None,False),
])
def test_process_default_auth_absence_does_not_deny_another_context_or_protocol_probe(tmp_path,overrides,resume,required):
    script=peer(tmp_path,{'result':{'requiresOpenaiAuth':True,'account':None}})
    connector=CodexAppServerConnector(command=[sys.executable,str(script)],cwd=str(tmp_path),env={},
        handshake_timeout_s=2,thread_start_overrides=overrides,require_authentication=required)
    try:
        session=connector.start(owning_agent_id='agent',resume_thread_id=resume)
        assert session.metadata['thread_id']=='synthetic-thread'
        observed=messages(tmp_path)
        assert [m['method'] for m in observed]==['initialize','initialized','account/read',
            'thread/resume' if resume else 'thread/start']
        assert observed[2]['params']=={'refreshToken':False}
        assert all(observed[3]['params'][k]==v for k,v in overrides.items())
        assert 'account' not in session.metadata
    finally:connector.close()


@pytest.mark.parametrize('overrides',[{}, {'config':{}}, {'config':{'model_reasoning_effort':'medium'}},
    {'config':{'features.default_mode_request_user_input':True}}])
def test_neutral_core_configuration_keeps_missing_login_preflight(tmp_path,overrides):
    script=peer(tmp_path,{'result':{'requiresOpenaiAuth':True,'account':None}})
    connector=CodexAppServerConnector(command=[sys.executable,str(script)],cwd=str(tmp_path),env={},
        handshake_timeout_s=2,thread_start_overrides=overrides)
    try:
        with pytest.raises(NativeAdapterError) as caught:connector.start(owning_agent_id='agent')
        assert caught.value.details=={'reason':'provider_auth_required'}
        assert [m['method'] for m in messages(tmp_path)]==['initialize','initialized','account/read']
    finally:connector.close()
