"""Explicit native decisions for Claude MCP calls; no implicit allow."""
import pytest
from nexus_connector_core import CoreError
from nexus_connector_core.decision_bridge_r4 import native_request_action
from nexus_connector_core.native.adapter_types import (
    HarnessCapabilities, HarnessSession, RuntimeCommandNotSent)
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector


def connector():
    native=ClaudeCodeStreamConnector(binary="claude")
    native.native_approvals_enabled=True
    native._session=HarnessSession("session","claude_code","agent","RUNNING",
        HarnessCapabilities(False,"IMMEDIATE",False,False,True),"2026-09-30T00:00:00Z")
    native._approval_turn_active=True
    native._approval_generation=3
    return native


@pytest.mark.parametrize("decision,behavior",[("accept","allow"),("decline","deny")])
def test_mcp_permission_needs_one_explicit_matching_decision(decision,behavior):
    native=connector()
    sent=[]
    native._write_json=sent.append
    arguments={"project_root":"workspace","agent_id":"subject","handoff_id":"work"}
    native._handle_permission_request({"request_id":"request","request":{
        "subtype":"can_use_tool","tool_name":"mcp__nexus_0123456789abcdef__handoff_get",
        "tool_use_id":"tool-1","input":arguments}})
    assert sent==[]
    request=native._approval_requests["request"]["request"]
    assert native_request_action(request)=="approval.decide"
    forged={**request,"params":{**request["params"],"tool_name":"mcp__other__handoff_get"}}
    with pytest.raises(RuntimeCommandNotSent):
        native.reply_native_approval("session",forged,decision)
    assert sent==[]
    native.reply_native_approval("session",request,decision)
    response=sent[0]["response"]["response"]
    assert response["behavior"]==behavior
    if decision=="accept": assert response["updatedInput"]==arguments
    with pytest.raises(RuntimeCommandNotSent):
        native.reply_native_approval("session",request,decision)
    assert len(sent)==1


@pytest.mark.parametrize("name",["mcp__server__", "mcp__server__tool name",
    "mcp__server__tool;command","mcp__server__"+"x"*256, "", True])
def test_invalid_mcp_permission_names_are_not_actionable(name):
    native=connector()
    sent=[]
    native._write_json=sent.append
    params={"subtype":"can_use_tool","tool_name":name,"tool_use_id":"tool-1","input":{}}
    native._handle_permission_request({"request_id":"bad","request":params})
    assert not native._approval_requests
    assert sent[0]["response"]["subtype"]=="error"
    with pytest.raises(CoreError):
        native_request_action({"method":"control_request:can_use_tool","params":params,
                               "local_generation":3})


@pytest.mark.parametrize("extra",[(),("--model","qualified-model"),
    ("--permission-mode","default"),("--permission-mode","bypassPermissions"),
    ("--strict-mcp-config","--mcp-config",'{"mcpServers":{}}')])
def test_stream_configuration_keeps_stdio_permission_channel(extra,tmp_path,monkeypatch):
    import nexus_connector_core.native.adapters.claude_code_stream as module
    native=ClaudeCodeStreamConnector(binary="claude",argv=(*module._DEFAULT_ARGV,*extra),cwd=str(tmp_path))
    native.native_approvals_enabled=True
    monkeypatch.setattr(module,"claude_version_observation",lambda *a,**kw:{"native_version":"technical"})
    seen=[]
    class SpawnObserved(Exception): pass
    def spawn(argv,**kwargs):
        seen.append(argv)
        raise SpawnObserved()
    monkeypatch.setattr(module,"spawn_owned_process",spawn)
    with pytest.raises(SpawnObserved):
        native.start(owning_agent_id="agent")
    assert tuple(seen[0])==("claude",*module._DEFAULT_ARGV,*extra,"--permission-prompt-tool","stdio")


def _bridge_categories(native, requests):
    """Run real adapter requests through the Core bridge; return event categories."""
    import asyncio
    from nexus_connector_core.native.adapter_types import HarnessEvent
    from nexus_connector_core.native.redaction import NativeSecretRedactor
    from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession
    from test_native_runtime_bridge import context
    emitted = []
    native._emit = lambda kind, name, payload: emitted.append(HarnessEvent(
        "session", "claude_code", kind, name, "2026-09-30T00:00:00Z", payload))
    native._write_json = lambda value: pytest.fail("a request must wait for the operator")
    for request_id, params in requests:
        native._handle_permission_request({"request_id": request_id, "request": params})
    native.events = lambda: iter(emitted)

    async def run():
        bridge = CopiedAdapterSession(native, native._session, session_id="bridge-session",
            stream_epoch="epoch", context=context(), redactor=NativeSecretRedactor([]))
        bridge._active_operation_id = "turn-operation"
        try:
            return [item async for item in bridge.events()]
        finally:
            bridge._control_executor.shutdown(wait=True)
            bridge._force_executor.shutdown(wait=True)
    return [(item.category, item.operation_id, "native_approval" in item.payload,
             "native_approval_display" in item.payload) for item in asyncio.run(run())]


def test_default_mode_permission_prompt_and_question_become_operator_requests():
    native = connector()
    question = {"questions": [{"question": "Which one?", "header": "Pick", "multiSelect": False,
        "options": [{"label": "a", "description": "A"}, {"label": "b", "description": "B"}]}]}
    result = _bridge_categories(native, [
        ("permission", {"subtype": "can_use_tool", "tool_name": "Bash", "tool_use_id": "t1",
                        "input": {"command": "touch file"}}),
        ("question", {"subtype": "can_use_tool", "tool_name": "AskUserQuestion", "tool_use_id": "t2",
                      "input": question})])
    assert result == [("approval_request", "turn-operation", True, True),
                      ("input_request", "turn-operation", True, True)]


def test_permission_prompt_is_ignored_without_native_approvals():
    native = connector()
    native.native_approvals_enabled = False
    sent = []
    native._write_json = sent.append
    native._handle_permission_request({"request_id": "request", "request": {
        "subtype": "can_use_tool", "tool_name": "Bash", "tool_use_id": "t1", "input": {}}})
    assert not native._approval_requests
    assert sent[0]["response"]["subtype"] == "error"
