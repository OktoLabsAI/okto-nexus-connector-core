"""Terminal native failures remain correlated and carry safe diagnostic codes."""
import asyncio

import pytest

from nexus_connector_core import OperationKey
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel
from nexus_connector_core.models import Operation
from nexus_connector_core.native.adapter_types import HarnessEvent, HarnessSession, HarnessCapabilities
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession
from test_native_runtime_bridge import FakeCopiedConnector, context


@pytest.mark.parametrize("case,expected", [
    ("claude_auth", "PROVIDER_AUTH_REQUIRED"),
    ("claude_error", "NATIVE_OPERATION_FAILED"),
    ("claude_text", "NATIVE_OPERATION_FAILED"),
    ("claude_forged", "NATIVE_OPERATION_FAILED"),
    ("codex_auth", "PROVIDER_AUTH_REQUIRED"),
    ("codex_http401", "PROVIDER_AUTH_REQUIRED"),
    ("codex_http403", "NATIVE_OPERATION_FAILED"),
    ("codex_unknown401", "NATIVE_OPERATION_FAILED"),
])
def test_terminal_failure_is_durable_and_scoped(tmp_path, case, expected):
    harness = "codex" if case.startswith("codex") else "claude_code"
    def event(kind, native, payload, **kwargs):
        return HarnessEvent("native-session", harness, kind, native, "2026-10-01T00:00:00Z", payload, **kwargs)
    class Connector(FakeCopiedConnector):
        delivery_event_phase = staticmethod(CodexAppServerConnector.delivery_event_phase if harness == "codex" else ClaudeCodeStreamConnector.delivery_event_phase)
        delivery_outcome = staticmethod(CodexAppServerConnector.delivery_outcome if harness == "codex" else ClaudeCodeStreamConnector.delivery_outcome)
        def events(self):
            if harness == "codex":
                yield event("turn_started", "turn/started", {"turn": {"id": "native-turn"}}, turn_id="native-turn")
                info = {
                    "codex_auth": "unauthorized",
                    "codex_http401": {"httpConnectionFailed": {"httpStatusCode": 401}},
                    "codex_http403": {"httpConnectionFailed": {"httpStatusCode": 403}},
                    "codex_unknown401": {"unknownFailure": {"httpStatusCode": 401}},
                }[case]
                yield event("turn_completed", "turn/completed",
                    {"turn": {"status": "failed", "error": {"codexErrorInfo": info}}},
                    turn_id="native-turn")
            elif case == "claude_error":
                yield event("error", "result:error_during_execution", {"is_error": True})
            else:
                payload = {"raw": {"error": "authentication_failed", "is_api_error_message": True}} if case == "claude_auth" else {"text": "authentication_failed"}
                yield event("output_delta", "assistant", payload)
                yield event("turn_completed", "result:success", {"is_error": True, "delivery_error_code": "PROVIDER_AUTH_REQUIRED"} if case == "claude_forged" else {"is_error": True})

    async def run():
        connector = Connector()
        session = HarnessSession("native-session", harness, "agent", "RUNNING",
            HarnessCapabilities(False, None, False, False, True), "2026-10-01T00:00:00Z")
        bridge = CopiedAdapterSession(connector, session, session_id="session", stream_epoch="epoch", context=context())
        journal = SQLiteJournal(tmp_path / "failure.db")
        key = OperationKey("srv", "exe", "turn")
        try:
            async def effect():
                await bridge.send("send_turn", {"text": "hello"}, "turn")
                return "native-turn"
            await OperationKernel(journal).execute(Operation("turn", "session", "turn.submit", {"text": "hello"}), context(), effect)
            events = []
            async for value in bridge.events():
                events.append(await journal.record_event(value))
            terminal = events[-1]
            assert terminal.category == "turn_state"
            assert terminal.operation_id == "turn"
            assert terminal.payload["delivery_outcome"] == "failed"
            receipt = await journal.get_receipt(key)
            assert receipt.stage == "FAILED"
            assert receipt.error_code == expected
            assert receipt.possible_effect and not receipt.retry_safe
            assert not bridge.active_turn()
            if harness == "codex":
                following = [
                    event("turn_started", "turn/started", {"turn": {"id": "next-native"}}, turn_id="next-native"),
                    event("turn_completed", "turn/completed", {"turn": {"status": "completed"}}, turn_id="next-native")]
            else:
                following = [event("turn_completed", "result:success", {"is_error": False})]
            connector.events = lambda: iter(following)
            async def next_effect():
                await bridge.send("send_turn", {"text": "next"}, "next")
                return "next-native"
            await OperationKernel(journal).execute(
                Operation("next", "session", "turn.submit", {"text": "next"}), context(), next_effect)
            async for value in bridge.events():
                await journal.record_event(value)
            following_receipt = await journal.get_receipt(OperationKey("srv", "exe", "next"))
            assert following_receipt.stage == "SUCCEEDED" and following_receipt.error_code is None
        finally:
            await bridge.force_stop()
            journal.close()
    asyncio.run(run())


@pytest.mark.parametrize("fault,stage,code", [
    ("auth", "FAILED", "PROVIDER_AUTH_REQUIRED"),
    ("other", "FAILED", "NATIVE_OPERATION_FAILED"),
    ("missing_id", "OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
    ("missing_command", "OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
])
def test_pi_rejection_preserves_known_failure_without_inventing_not_sent(tmp_path, fault, stage, code):
    from nexus_connector_core.native.adapters.pi import PiRpcConnector
    from nexus_connector_core.native.adapter_types import NativeAdapterError
    response = dict(type="response", id="core-1", command="prompt", success=False,
        error="No API key found for anthropic.\n\nUse /login to log into a provider via OAuth or API key. See:\n  providers.md")
    if fault == "other":
        response["error"] = "Unrecognized provider failure."
    elif fault == "missing_id":
        response.pop("id")
    elif fault == "missing_command":
        response.pop("command")
    class Connector(FakeCopiedConnector):
        def send(self, session, command):
            super().send(session, command)
            if command.verb == "send_turn":
                PiRpcConnector._require_accepted(response, "prompt")
    async def run():
        connector = Connector()
        session = HarnessSession("native-session", "pi", "agent", "RUNNING",
            HarnessCapabilities(False, None, False, False, True), "2026-10-01T00:00:00Z")
        bridge = CopiedAdapterSession(connector, session, session_id="session", stream_epoch="epoch", context=context())
        journal = SQLiteJournal(tmp_path / "rejected.db")
        operation = Operation("turn", "session", "turn.submit", {"text": "hello"})
        async def effect():
            await bridge.send("send_turn", {"text": "hello"}, "turn")
        try:
            kernel = OperationKernel(journal)
            if stage == "FAILED":
                await kernel.execute(operation, context(), effect)
                assert not bridge.active_turn()
            else:
                with pytest.raises(NativeAdapterError):
                    await kernel.execute(operation, context(), effect)
            receipt = await journal.get_receipt(OperationKey("srv", "exe", "turn"))
            assert receipt.stage == stage and receipt.error_code == code
            assert receipt.possible_effect and not receipt.retry_safe
            assert await kernel.execute(operation, context(), effect) == receipt
            assert len(connector.sent) == 1
        finally:
            await bridge.force_stop()
            journal.close()
    asyncio.run(run())
