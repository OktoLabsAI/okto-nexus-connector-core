"""Pi 0.87.1 RPC dialog grammar, verified against installed rpc-types/rpc-mode."""
import pytest
from nexus_connector_core import native_input_response


@pytest.mark.parametrize("method,extra,response", [
    ("select", {"options": ["Blue", "Green"]}, {"value": "Blue"}),
    ("confirm", {"message": "Proceed?"}, {"confirmed": False}),
    ("input", {"placeholder": "Answer"}, {"value": "Custom answer"}),
    ("editor", {"prefill": "Draft"}, {"value": ""}),
])
def test_pi_dialog_returns_native_response_and_preserves_explicit_values(method, extra, response):
    request = dict(method="extension_ui_request", request_id="question-1",
                   params=dict(method=method, title="Question", **extra))
    assert native_input_response(request, response, approved=True) == {
        "type": "extension_ui_response", "id": "question-1", **response}
    assert native_input_response(request, None, approved=False) == {
        "type": "extension_ui_response", "id": "question-1", "cancelled": True}


@pytest.mark.parametrize("method,extra,response", [
    ("select", {"options": ["Blue", "Green"]}, {"value": "Violet"}),
    ("select", {"options": ["Blue", "Blue"]}, {"value": "Blue"}),
    ("confirm", {"message": "Proceed?"}, {"confirmed": "false"}),
    ("input", {}, {"value": "ok", "id": "other-question"}),
    ("input", {}, {"cancelled": True}),
    ("editor", {}, {"value": ["Blue", "Green"]}),
    ("notify", {"message": "Informational"}, {"value": "ok"}),
])
def test_pi_dialog_rejects_wrong_contract(method, extra, response):
    request = dict(method="extension_ui_request", request_id="question-1",
                   params=dict(method=method, title="Question", **extra))
    with pytest.raises(ValueError):
        native_input_response(request, response, approved=True)


def test_pi_request_is_bound_to_generation_content_and_single_reply():
    from nexus_connector_core.native.pi_inputs import PiInputRequests
    from nexus_connector_core.decision_bridge_r4 import native_request_action
    registry = PiInputRequests()
    native = dict(type="extension_ui_request", id="one", method="input", title="Question")
    assert registry.capture(native) is None
    registry.start_turn()
    request = registry.capture(native)
    assert registry.owns(request)
    assert native_request_action(request) == "input.provide"
    assert registry.capture(native) is None
    with pytest.raises(ValueError):
        registry.response(dict(request, params={"method": "input", "title": "Changed"},
                               operator_response={"value": "answer"}), "accept")
    assert registry.owns(request)
    assert registry.response(dict(request, operator_response={"value": "answer"}), "accept")["value"] == "answer"
    with pytest.raises(ValueError):
        registry.response(dict(request, operator_response={"value": "answer"}), "accept")
    second = registry.capture(dict(native, id="two"))
    registry.end_turn()
    registry.start_turn()
    assert not registry.owns(second)
    with pytest.raises(ValueError):
        registry.response(dict(second, operator_response={"value": "answer"}), "accept")


def test_pi_explicit_timeout_blocks_late_reply(monkeypatch):
    from nexus_connector_core.native.pi_inputs import PiInputRequests
    clock = [100.0]
    monkeypatch.setattr("nexus_connector_core.native.pi_inputs.time.monotonic", lambda: clock[0])
    registry = PiInputRequests()
    registry.start_turn()
    request = registry.capture(dict(id="short", method="input", title="Short", timeout=1000))
    assert registry.owns(request)
    clock[0] += 1
    assert not registry.owns(request)
    with pytest.raises(ValueError):
        registry.response(dict(request, operator_response={"value": "late"}), "accept")
    assert registry.capture(dict(id="default", method="input", title="Default", timeout=None))


def test_pi_input_passes_core_durable_request_and_single_decision(tmp_path):
    import asyncio
    from nexus_connector_core import LaunchIntent, OpenOperation, NativeApprovalOperation, ShutdownPolicy
    from test_runtime import make_runtime, context, FakeNative, _emit_durable_native_request
    from nexus_connector_core.native.pi_inputs import PiInputRequests

    class Native(FakeNative):
        def __init__(self):
            super().__init__()
            self.inputs = PiInputRequests()
            self.inputs.start_turn()
            self.replies = []

        async def reply_native_approval(self, request, decision, response):
            assert self.inputs.current(request)
            self.replies.append(self.inputs.response(dict(request, operator_response=response), decision))

    async def run():
        runtime, journal, factory = make_runtime(tmp_path, adapter_id="pi_rpc")
        factory.native = Native()
        authority = context(actions={"runtime.open", "runtime.close", "input.provide"})
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", "pi_rpc"), authority)
            await runtime.open(OpenOperation("open", "session", "epoch", prepared), authority)
            request = factory.native.inputs.capture(dict(type="extension_ui_request", id="q1", method="input", title="Question"))
            await _emit_durable_native_request(runtime, factory.native, request)
            operation = NativeApprovalOperation("answer", "session", request, "accept", {"value": "typed answer"})
            receipt = await runtime.decide_native_approval(operation, authority)
            assert receipt.stage == "SUBMITTED"
            assert await runtime.decide_native_approval(operation, authority) == receipt
            assert factory.native.replies == [{"type": "extension_ui_response", "id": "q1", "value": "typed answer"}]
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()
    asyncio.run(run())
