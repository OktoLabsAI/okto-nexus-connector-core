"""Operational approval proposals survive display redaction unchanged."""
import asyncio
from dataclasses import replace
import hashlib
import json
import pytest

from nexus_connector_core.native.adapter_types import HarnessEvent, HarnessSession, HarnessCapabilities
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession
from nexus_connector_core.native.redaction import NativeSecretRedactor
from nexus_connector_core.protocol import canonical_json
from test_native_runtime_bridge import context


@pytest.mark.parametrize("correlated",[True,False])
def test_operational_request_is_correlated_frozen_and_separate_from_display(correlated):
    params={"subtype":"can_use_tool","tool_name":"mcp__nexus_session__handoff_get",
            "tool_use_id":"tool","input":{"authorization":"Bearer protected-value","handoff_id":"work"}}
    original={"schema_version":1,"request_id":"nxs_native_identifier",
        "method":"control_request:can_use_tool","params":params,"local_generation":3,
        "request_hash":hashlib.sha256(json.dumps(["nxs_native_identifier",params],
            sort_keys=True,separators=(",",":")).encode()).hexdigest()}
    event=HarnessEvent("native","claude_code","tool_activity","control_request:can_use_tool",
                       "2026-09-30T00:00:00Z",{"native_approval":original})
    class Native:
        def events(self): return iter([event])
        def native_approval_request(self,item):
            assert item is event
            return original if correlated else None
    native_session=HarnessSession("native","claude_code","agent","RUNNING",
        HarnessCapabilities(False,"IMMEDIATE",False,False,True),"2026-09-30T00:00:00Z")
    async def run():
        bridge=CopiedAdapterSession(Native(),native_session,session_id="session",stream_epoch="epoch",
            context=context(),redactor=NativeSecretRedactor(["protected-value"]))
        bridge._active_operation_id="turn-operation"
        try:
            events=[item async for item in bridge.events()]
        finally:
            bridge._control_executor.shutdown(wait=True)
            bridge._force_executor.shutdown(wait=True)
        result=events[0]
        if correlated:
            assert result.category=="approval_request"
            assert result.operation_id=="turn-operation"
            assert canonical_json(result.payload["native_approval"])==canonical_json(original)
            assert "protected-value" not in json.dumps(result.payload["native_approval_display"])
            params["input"]["handoff_id"]="changed"
            assert result.payload["native_approval"]["params"]["input"]["handoff_id"]=="work"
        else:
            assert result.category=="tool_activity"
            assert "native_approval" not in result.payload
            assert "native_approval_display" not in result.payload
            assert "protected-value" not in json.dumps(result.payload)
    asyncio.run(run())
