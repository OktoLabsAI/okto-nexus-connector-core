"""Selected version observation at the real factory boundary."""
import asyncio
from dataclasses import replace
import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.native.adapter_types import HarnessSession, HarnessCapabilities
from test_native_runtime_bridge import context
from test_process_http_configuration import prepared


@pytest.mark.parametrize("fault",["none","unqualified","expired_before_probe","expired_after_probe","content"])
def test_missing_version_is_observed_before_secrets_with_frontier_guards(tmp_path,monkeypatch,fault):
    import nexus_connector_core.discovery as discovery
    import nexus_connector_core.native.runtime_bridge as bridge
    binary=tmp_path/"provider.exe"
    binary.write_bytes(b"selected")
    launch=prepared("codex_app_server", tmp_path)
    launch=replace(launch,candidate=replace(launch.candidate,version=None,executable=str(binary)),
                   argv=(str(binary),"app-server"),cwd=str(tmp_path))
    now=[1]
    seen=[]
    ctx=replace(context(),lease_deadline_monotonic=100)
    monkeypatch.setattr(bridge,"qualified_build",lambda kind,version,*a,**kw:version=="qualified")
    def observe(candidate,adapter,*,cwd,env,before_observe):
        seen.append("probe")
        assert candidate is launch.candidate and adapter=="codex_app_server"
        if fault=="expired_before_probe": now[0]=101
        before_observe()
        seen.append("version_process")
        if fault=="expired_after_probe": now[0]=101
        if fault=="content": binary.write_bytes(b"changed content")
        return replace(candidate,version="unknown" if fault=="unqualified" else "qualified")
    monkeypatch.setattr(discovery,"_probe_selected_version",observe)
    class Native:
        def __init__(self,**kwargs): seen.append("native")
        def start(self,*,owning_agent_id):
            return HarnessSession("native","codex",owning_agent_id,"STARTING",
                HarnessCapabilities(False,None,False,False,True),"2026-09-30T00:00:00Z")
        def close(self): pass
    monkeypatch.setattr(bridge,"load_adapter",lambda _:Native)
    async def environment(value):
        assert value is launch
        seen.append("secrets")
        return {}
    async def run():
        factory=CopiedAdapterFactory(environment,clock=lambda:now[0])
        try:
            if fault=="none":
                await factory.open(launch,"session",ctx,stream_epoch="epoch")
            else:
                expected={"unqualified":"NATIVE_VERSION_UNQUALIFIED","content":"PROFILE_DRIFT"}.get(fault,"AGENT_REVOKED")
                with pytest.raises(CoreError,match=expected):
                    await factory.open(launch,"session",ctx,stream_epoch="epoch")
        finally:
            factory.close()
    asyncio.run(run())
    assert launch.candidate.version is None
    if fault=="none":
        assert seen==["probe","version_process","secrets","native"]
    else:
        assert "secrets" not in seen and "native" not in seen
        if fault=="expired_before_probe": assert "version_process" not in seen
