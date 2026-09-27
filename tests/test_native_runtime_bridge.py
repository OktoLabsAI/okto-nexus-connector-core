import asyncio
import json
import os
import queue
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import CoreError, ExecutionContext, SessionKey
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel
from nexus_connector_core.models import (
    ControlOperation, EventCursor, InstallationCandidate, LaunchIntent, NativeApprovalOperation, OpenOperation, Operation, OperationKey,
    PreparedLaunch, ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.native.adapter_types import (
    ErrorCode, HarnessCapabilities, HarnessEvent, HarnessSession,
    NativeAdapterError, RuntimeCommandNotSent,
)
from nexus_connector_core.native.adapters.pi import PiRpcConnector
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector
from nexus_connector_core.native.adapters.codex import _ThreadState
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory, CopiedAdapterSession
from nexus_connector_core.native.native_inputs import USER_INPUT
from nexus_connector_core.native.process import (
    snapshot_owned_process_birth, spawn_owned_process,
)
from nexus_connector_core.native.legacy_environment import child_environment as legacy_child_environment
from nexus_connector_core.pi_extension_resource import PiNativeActionLaunch, pi_extension_path
from nexus_connector_core.harness_config import harness_http_template
from nexus_connector_core.runtime import LocalRuntimeCore


@pytest.mark.skipif(sys.platform not in {"win32", "linux"},
                    reason="managed process backend unqualified")
def test_copied_factory_open_persists_real_owned_child_birth(tmp_path, monkeypatch):
    import nexus_connector_core.native.runtime_bridge as bridge_module
    import nexus_connector_core.native.adapters.codex as codex_module

    created = []

    class SyntheticCodex:
        def __init__(self, *, command, cwd, env):
            self.cwd = cwd
            self._proc = None
            created.append(self)

        def start(self, *, owning_agent_id):
            self._proc = spawn_owned_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=self.cwd, env=dict(os.environ), text=True)
            return HarnessSession("native-session", "codex", owning_agent_id,
                                  "STARTING", HarnessCapabilities(
                                      False, None, False, False, True),
                                  "2026-09-25T00:00:00Z")

        def events(self):
            while self._proc is not None and self._proc.poll() is None:
                time.sleep(0.02)
                if False:
                    yield None

        def send(self, session, command):
            if command.verb == "end":
                self.close()

        def close(self):
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()
                self._proc.wait(timeout=10)

        force_stop = close

        def observe_lifecycle(self, session):
            return {"stop_observed": self._proc is not None and
                    self._proc.poll() is not None}

    monkeypatch.setattr(bridge_module, "qualified_build",
                         lambda *args, **kwargs: True)
    monkeypatch.setattr(codex_module, "CodexAppServerConnector", SyntheticCodex)

    async def run():
        candidate = InstallationCandidate(
            "codex_app_server", sys.executable, fingerprint(Path(sys.executable)),
            "explicit", "selected", version="synthetic")
        journal = SQLiteJournal(tmp_path / "birth-factory.db")

        async def environment(_prepared):
            return {}

        runtime = LocalRuntimeCore(
            journal, CopiedAdapterFactory(environment),
            candidates={"codex_app_server": candidate},
            workspace_roots={"ws": str(tmp_path)})
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), context())
            receipt = await runtime.open(
                OpenOperation("open-real-birth", "session", "epoch", prepared),
                context())
            assert receipt.stage == "SUBMITTED"
            key = SessionKey("srv", "exe", "session")
            record = await runtime.process_birth(key)
            assert record is not None
            assert record.opening_operation_id == "open-real-birth"
            assert record.evidence == snapshot_owned_process_birth(created[0]._proc)
            observation = await runtime.observe_process_birth(key)
            assert observation.record == record
            assert observation.state == "MATCHING_LIVE"
            await runtime.shutdown(ShutdownPolicy(1, 1))
            assert (await runtime.observe_process_birth(key)).state in {
                "NOT_RUNNING", "NOT_OBSERVED"}
        finally:
            for connector in created:
                connector.close()
            journal.close()

    asyncio.run(run())


def context():
    return ExecutionContext("srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                            time.monotonic() + 60,
                            frozenset({"runtime.open", "turn.submit"}))


class FakeCopiedConnector:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, session, command):
        self.sent.append(command)
        if command.verb == "end":
            self.closed = True

    def events(self):
        yield HarnessEvent("native-session", "claude_code", "output_delta",
                           "assistant", "2026-09-25T00:00:00Z",
                           {"delta": "hi"}, operation_id="op-1")

    def close(self):
        self.closed = True

    def force_stop(self):
        self.closed = True

    def observe_lifecycle(self, session):
        return {"stop_observed": self.closed}


def test_codex_approval_reply_uses_original_pending_method():
    class Replies:
        def __init__(self):
            self.sent = []

        def reply_result(self, request_id, result):
            self.sent.append((request_id, result))

    connector = CodexAppServerConnector()
    connector._transport = Replies()
    connector._sessions_by_id["session"] = _ThreadState(
        "session", "thread", "agent", active_turn_id="turn")
    original = {
        "request_id": 7, "request_hash": "request-hash", "method": USER_INPUT,
        "params": {
            "threadId": "thread", "turnId": "turn", "isBlocking": True,
            "questions": [{"id": "q", "header": "Choice", "question": "Proceed?",
                           "options": [{"label": "yes", "description": "Proceed"}]}],
        },
    }
    connector._approval_requests[json.dumps(7)] = {
        "pending": True, "session_id": "session", "request": original}
    forged = {"request_id": 7, "request_hash": "request-hash",
              "method": "item/commandExecution/requestApproval"}
    with pytest.raises(RuntimeCommandNotSent, match="ended or changed"):
        connector.reply_native_approval("session", forged, "accept")
    assert connector._approval_requests[json.dumps(7)]["pending"]
    assert connector._transport.sent == []

    forged["method"] = USER_INPUT
    with pytest.raises(RuntimeCommandNotSent, match="explicit operator response"):
        connector.reply_native_approval("session", forged, "accept")
    forged["operator_response"] = {"answers": {"q": {"answers": ["yes"]}}}
    connector.reply_native_approval("session", forged, "accept")
    assert connector._transport.sent == [
        (7, {"answers": {"q": {"answers": ["yes"]}}})]


def test_claude_approval_reply_rejects_forged_tool_kind():
    connector = ClaudeCodeStreamConnector(binary="claude")
    connector._session = HarnessSession(
        "session", "claude_code", "agent", "RUNNING",
        HarnessCapabilities(False, "IMMEDIATE", False, False, True),
        "2026-09-25T00:00:00Z")
    connector._approval_turn_active = True
    connector._approval_generation = 3
    original = {
        "request_id": "request", "request_hash": "a" * 64,
        "method": "control_request:can_use_tool", "local_generation": 3,
        "params": {"tool_name": "Bash", "input": {"command": "true"}},
    }
    connector._approval_requests["request"] = {
        "request": original, "pending": True}
    sent = []
    connector._write_json = sent.append
    forged = {**original, "params": {"tool_name": "AskUserQuestion"}}
    with pytest.raises(RuntimeCommandNotSent, match="no longer belongs"):
        connector.reply_native_approval("session", forged, "accept")
    assert connector._approval_requests["request"]["pending"]
    assert sent == []
    connector.reply_native_approval("session", original, "decline")
    assert sent[0]["response"]["response"]["behavior"] == "deny"


@pytest.mark.skipif(sys.platform not in {"win32", "linux"},
                    reason="managed process backend unqualified")
@pytest.mark.parametrize("trigger,method,decision,response,expected_result", [
    ("TRIGGER_APPROVAL_HOLD", "item/commandExecution/requestApproval",
     "decline", None, {"decision": "decline"}),
    ("TRIGGER_INPUT_HOLD", "item/tool/requestUserInput", "accept",
     {"answers": {"answer": {"answers": ["operator-secret-answer-marker"]}}},
     {"answers": {"answer": {"answers": ["operator-secret-answer-marker"]}}}),
])
def test_codex_peer_approval_decision_is_durable_authorized_and_correlated(
        tmp_path, trigger, method, decision, response, expected_result):
    peer = Path(__file__).parent / "fixtures" / "codex_app_server_peer.py"
    log_path = tmp_path / "approval-peer.jsonl"
    binary = tmp_path / "synthetic-codex"
    binary.write_bytes(b"synthetic")

    class Factory:
        def __init__(self):
            self.connector = None

        async def open(self, prepared, session_id, authority, *, stream_epoch):
            connector = CodexAppServerConnector(
                command=(sys.executable, str(peer), str(log_path)),
                cwd=str(tmp_path), env={})
            connector.native_approvals_enabled = True
            self.connector = connector
            native_session = await asyncio.to_thread(
                connector.start, owning_agent_id=authority.agent_id)
            return CopiedAdapterSession(
                connector, native_session, session_id=session_id,
                stream_epoch=stream_epoch, context=authority)

    async def run():
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), fingerprint(binary),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "approval-peer.db")
        factory = Factory()
        runtime = LocalRuntimeCore(
            journal, factory, candidates={"codex_app_server": candidate},
            workspace_roots={"ws": str(tmp_path)})
        authority = replace(context(), allowed_actions=frozenset({
            "runtime.open", "turn.submit", "runtime.close",
            "approval.decide", "input.provide"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            await runtime.submit(
                TurnOperation("turn", "session", trigger),
                authority)

            async def pending_request():
                async for event in runtime.events(
                        EventCursor("srv", "exe", "session", "epoch")):
                    request = event.payload.get("native_approval")
                    if request is not None:
                        return request

            request = await asyncio.wait_for(pending_request(), timeout=5)
            assert request["method"] == method
            denied_context = replace(
                authority, allowed_actions=frozenset({"runtime.open"}))
            with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("unauthorized", "session", request,
                                            "decline"), denied_context)
            assert await journal.get_receipt(
                OperationKey("srv", "exe", "unauthorized")) is None

            receipt = await runtime.decide_native_approval(
                NativeApprovalOperation("decision", "session", request,
                                        decision, response), authority)
            assert receipt.stage == "SUBMITTED" and receipt.possible_effect
            if response is not None:
                assert "operator-secret-answer-marker" not in "\n".join(
                    journal._run_sync(lambda db: "".join(db.iterdump())))

            async def completed_and_logged():
                while True:
                    turn = await journal.get_receipt(
                        OperationKey("srv", "exe", "turn"))
                    if (turn is not None and turn.stage == "SUCCEEDED" and
                            log_path.exists() and
                            "response_to_server_request" in log_path.read_text(
                                encoding="utf-8")):
                        return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(completed_and_logged(), timeout=5)
            lines = [json.loads(line) for line in log_path.read_text(
                encoding="utf-8").splitlines()]
            replies = [line["response_to_server_request"] for line in lines
                       if "response_to_server_request" in line]
            assert len(replies) == 1
            assert replies[0]["result"] == expected_result
            with pytest.raises(CoreError, match="NATIVE_REQUEST_NOT_OBSERVED") as stale:
                await runtime.decide_native_approval(
                    NativeApprovalOperation("late", "session", request,
                                            decision, response), authority)
            assert stale.value.retry_safe and not stale.value.possible_effect
            assert await journal.get_receipt(
                OperationKey("srv", "exe", "late")) is None
        finally:
            await runtime.shutdown(ShutdownPolicy(1, 1))
            journal.close()

    asyncio.run(run())


def test_copied_bridge_replies_only_to_current_native_approval_turn():
    class ApprovalConnector(FakeCopiedConnector):
        def __init__(self):
            super().__init__()
            self.replies = []

        def events(self):
            yield HarnessEvent(
                "native-session", "codex", "turn_started", "turn/started",
                "2026-09-25T00:00:00Z", {}, turn_id="turn-1",
                delivery_phase="started")

        def reply_native_approval(self, session_id, request, decision):
            self.replies.append((session_id, request, decision))

    async def run():
        connector = ApprovalConnector()
        harness = HarnessSession(
            "native-session", "codex", "agent", "STARTING",
            HarnessCapabilities(False, "IMMEDIATE", False, False, True),
            "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(
            connector, harness, session_id="public-session",
            stream_epoch="epoch", context=context())
        request = {"request_id": 7, "request_hash": "a" * 64,
                   "method": "item/commandExecution/requestApproval",
                   "params": {"turnId": "turn-1"}}
        with pytest.raises(RuntimeCommandNotSent, match="not active"):
            await bridge.reply_native_approval(request, "decline", None)
        await bridge.send("send_turn", {"text": "hello"}, "op-1")
        await anext(bridge.events())
        with pytest.raises(RuntimeCommandNotSent, match="turn changed"):
            await bridge.reply_native_approval(
                {**request, "params": {"turnId": "old"}}, "decline", None)
        await bridge.reply_native_approval(request, "cancel", None)
        assert connector.replies == [
            ("native-session", request, "decline")]

    asyncio.run(run())


def test_codex_prewrite_refusal_is_durable_safe_failure_and_reusable(tmp_path):
    class RefusingOnce(FakeCopiedConnector):
        def send(self, session, command):
            if not self.sent:
                self.sent.append(command)
                raise NativeAdapterError(ErrorCode.CONFLICT, "turn still active",
                                         {"not_sent": True})
            self.sent.append(command)

    async def run():
        connector = RefusingOnce()
        harness = HarnessSession("native-session", "codex", "agent", "STARTING",
                                 HarnessCapabilities(False, None, False, False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        journal = SQLiteJournal(tmp_path / "journal.db")
        try:
            kernel = OperationKernel(journal)
            first = Operation("op-safe", "public-session", "turn.submit", {"text": "hello"})

            async def first_effect():
                await bridge.send("send_turn", {"text": "hello"}, first.operation_id)

            with pytest.raises(CoreError, match="CONFLICT") as refused:
                await kernel.execute(first, context(), first_effect)
            assert refused.value.retry_safe and not refused.value.possible_effect
            receipt = await journal.get_receipt(OperationKey("srv", "exe", "op-safe"))
            assert receipt.stage == "FAILED" and not receipt.possible_effect
            assert not bridge.active_turn()

            second = Operation("op-later", "public-session", "turn.submit", {"text": "later"})

            async def second_effect():
                await bridge.send("send_turn", {"text": "later"}, second.operation_id)

            accepted = await kernel.execute(second, context(), second_effect)
            assert accepted.stage == "SUBMITTED" and bridge.active_turn()
        finally:
            journal.close()

    asyncio.run(run())


def test_unmarked_native_error_keeps_possible_effect_unknown(tmp_path):
    class Ambiguous(FakeCopiedConnector):
        def send(self, session, command):
            raise NativeAdapterError(ErrorCode.INTERNAL_ERROR, "write may have occurred", {})

    async def run():
        harness = HarnessSession("native-session", "codex", "agent", "STARTING",
                                 HarnessCapabilities(False, None, False, False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(Ambiguous(), harness, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        journal = SQLiteJournal(tmp_path / "journal.db")
        try:
            operation = Operation("op-unknown", "public-session", "turn.submit",
                                  {"text": "hello"})

            async def effect():
                await bridge.send("send_turn", {"text": "hello"}, operation.operation_id)

            with pytest.raises(NativeAdapterError):
                await OperationKernel(journal).execute(operation, context(), effect)
            receipt = await journal.get_receipt(OperationKey("srv", "exe", "op-unknown"))
            assert receipt.stage == "OUTCOME_UNKNOWN" and receipt.possible_effect
            assert bridge.active_turn()
        finally:
            journal.close()

    asyncio.run(run())


def test_copied_adapter_maps_native_session_and_payload():
    async def run():
        connector = FakeCopiedConnector()
        harness = HarnessSession("native-session", "claude_code", "agent",
                                 "STARTING", HarnessCapabilities(False, None, False,
                                                                 False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        await bridge.send("send_turn", {"text": "hello"}, "op-1")
        assert bridge.active_turn()
        assert connector.sent[0].payload == {"content": "hello"}
        assert connector.sent[0].session_id == "native-session"
        events = [item async for item in bridge.events()]
        assert len(events) == 1
        assert events[0].session_id == "public-session"
        assert events[0].native_type == "assistant"
        assert events[0].operation_id == "op-1"
        assert bridge.active_turn()
        assert await bridge.close() == "graceful"

    asyncio.run(run())


def test_copied_adapter_retries_close_after_unobserved_failure():
    class FlakyClose(FakeCopiedConnector):
        def __init__(self):
            super().__init__()
            self.close_calls = 0

        def send(self, session, command):
            self.sent.append(command)

        def close(self):
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("injected close failure")
            self.closed = True

    async def run():
        connector = FlakyClose()
        harness = HarnessSession("native-session", "claude_code", "agent",
                                 "STARTING", HarnessCapabilities(False, None, False,
                                                                 False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        with pytest.raises(RuntimeError, match="injected close failure"):
            await bridge.close()
        assert (await bridge.observe())[0] == "RUNNING"
        with pytest.raises(CoreError, match="SESSION_CLOSED"):
            await bridge.send("send_turn", {"text": "late"}, "late")
        assert await bridge.close() == "unknown"
        assert connector.close_calls == 2
        assert (await bridge.observe())[0] == "STOPPED"
        assert await bridge.close() == "already_closed"
        assert len([command for command in connector.sent
                    if command.verb == "end"]) == 1

    asyncio.run(run())


def test_copied_adapter_retries_close_when_stop_not_observed():
    class DelayedStop(FakeCopiedConnector):
        def __init__(self):
            super().__init__()
            self.close_calls = 0

        def send(self, session, command):
            self.sent.append(command)

        def close(self):
            self.close_calls += 1
            if self.close_calls == 2:
                self.closed = True

    async def run():
        connector = DelayedStop()
        harness = HarnessSession("native-session", "claude_code", "agent",
                                 "STARTING", HarnessCapabilities(False, None, False,
                                                                 False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        assert await bridge.close() == "unknown"
        assert (await bridge.observe())[0] == "RUNNING"
        assert await bridge.close() == "unknown"
        assert connector.close_calls == 2
        assert (await bridge.observe())[0] == "STOPPED"
        assert len([command for command in connector.sent
                    if command.verb == "end"]) == 1

    asyncio.run(run())


def test_copied_adapter_force_stop_fences_sends_and_observes_tree():
    async def run():
        connector = FakeCopiedConnector()
        harness = HarnessSession("native-session", "claude_code", "agent",
                                 "STARTING", HarnessCapabilities(False, None, False,
                                                                 False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        await bridge.force_stop()
        with pytest.raises(CoreError, match="SESSION_CLOSED"):
            await bridge.send("send_turn", {"text": "late"}, "late")
        assert (await bridge.observe())[0] == "STOPPED"
        assert await bridge.close() == "already_closed"

    asyncio.run(run())


@pytest.mark.parametrize("adapter_id", ["codex_app_server", "pi_rpc", "claude_stream"])
def test_copied_managed_peer_force_stop_observes_owned_tree(tmp_path, adapter_id):
    fixture_dir = Path(__file__).parent / "fixtures"

    async def run():
        if adapter_id == "codex_app_server":
            connector = CodexAppServerConnector(
                command=(sys.executable,
                         str(fixture_dir / "codex_app_server_peer.py"),
                         str(tmp_path / "codex-log.jsonl")),
                cwd=str(tmp_path), handshake_timeout_s=5)
        elif adapter_id == "pi_rpc":
            connector = PiRpcConnector(
                command=(sys.executable,
                         str(fixture_dir / "pi_rpc_peer.py"),
                         str(tmp_path / "pi-log.jsonl")),
                version_command=(sys.executable, "-c", "print('0.85.1')"),
                cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
        else:
            connector = ClaudeCodeStreamConnector(
                binary=sys.executable,
                argv=("-u", "-c", (fixture_dir / "claude_stream_peer.py").read_text(
                    encoding="utf-8")),
                cwd=str(tmp_path), env={"FAKE_CC_SCENARIO": "basic"})
        session = await asyncio.to_thread(connector.start, owning_agent_id="agent")
        bridge = CopiedAdapterSession(connector, session, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        await bridge.force_stop()
        async def stopped():
            while (await bridge.observe())[0] != "STOPPED":
                await asyncio.sleep(0.01)
        await asyncio.wait_for(stopped(), timeout=5)
        assert await bridge.close() == "already_closed"

    asyncio.run(run())


def test_copied_adapter_refuses_idle_and_stale_target_before_write():
    class TurnConnector(FakeCopiedConnector):
        def events(self):
            yield HarnessEvent("native-session", "codex", "turn_started",
                               "turn/started", "2026-09-25T00:00:00Z", {},
                               turn_id="native-turn-1")

    async def run():
        connector = TurnConnector()
        harness = HarnessSession("native-session", "codex", "agent",
                                 "STARTING", HarnessCapabilities(False, "IMMEDIATE",
                                                                 False, False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness, session_id="public-session",
                                      stream_epoch="epoch", context=context())
        with pytest.raises(RuntimeCommandNotSent, match="no active turn"):
            await bridge.send("interrupt", {}, "idle")
        assert connector.sent == []
        await bridge.send("send_turn", {"text": "hello"}, "op-1")
        assert len([event async for event in bridge.events()]) == 1
        with pytest.raises(RuntimeCommandNotSent, match="expected native turn") as exc:
            await bridge.send("interrupt", {}, "stale", expected_turn_id="old")
        assert exc.value.code == "STALE_TURN"
        assert len(connector.sent) == 1
        await bridge.send("interrupt", {}, "current", expected_turn_id="native-turn-1")
        assert connector.sent[-1].expected_turn_id == "native-turn-1"
        await bridge.close()

    asyncio.run(run())


@pytest.mark.parametrize("stale_terminal_first", [True, False])
def test_pi_terminal_needs_active_agent_start(stale_terminal_first):
    class TurnConnector(FakeCopiedConnector):
        def events(self):
            order = (["agent_settled", "agent_start"] if stale_terminal_first
                     else ["agent_start", "agent_settled"])
            for native_type in order:
                yield HarnessEvent(
                    "native-session", "pi",
                    "turn_completed" if native_type == "agent_settled" else "tool_activity",
                    native_type, "2026-09-25T00:00:00Z", {},
                    delivery_phase=("terminal" if native_type == "agent_settled"
                                    else "started"),
                    delivery_outcome=("success" if native_type == "agent_settled"
                                      else None))

    async def run():
        connector = TurnConnector()
        harness = HarnessSession("native-session", "pi", "agent", "STARTING",
                                 HarnessCapabilities(False, "NEXT_TURN_BOUNDARY",
                                                     True, False, True),
                                 "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness,
                                      session_id="public-session",
                                      stream_epoch="epoch", context=context())
        await bridge.send("send_turn", {"text": "hello"}, "op-1")
        if stale_terminal_first:
            with pytest.raises(CoreError, match="EVENT_OPERATION_MISMATCH") as exc:
                _ = [event async for event in bridge.events()]
            assert exc.value.possible_effect
            assert bridge.active_turn()
        else:
            events = [event async for event in bridge.events()]
            assert events[-1].operation_id == "op-1"
            assert events[-1].payload["delivery_phase"] == "terminal"
            assert not bridge.active_turn()
        await bridge.close()

    asyncio.run(run())


def test_pi_steer_targets_only_the_observed_active_agent_run():
    class TurnConnector(FakeCopiedConnector):
        def events(self):
            yield HarnessEvent("native-session", "pi", "tool_activity",
                               "agent_start", "2026-09-26T00:00:00Z", {},
                               delivery_phase="started")
            yield HarnessEvent("native-session", "pi", "turn_completed",
                               "agent_settled", "2026-09-26T00:00:00Z", {},
                               delivery_phase="terminal",
                               delivery_outcome="success")

    async def run():
        connector = TurnConnector()
        harness = HarnessSession("native-session", "pi", "agent", "STARTING",
                                 HarnessCapabilities(False, "NEXT_TURN_BOUNDARY",
                                                     True, False, True),
                                 "2026-09-26T00:00:00Z")
        bridge = CopiedAdapterSession(connector, harness,
                                      session_id="public-session",
                                      stream_epoch="epoch", context=context())
        with pytest.raises(RuntimeCommandNotSent, match="no active turn"):
            await bridge.send("steer", {"text": "early"}, "steer-idle")
        await bridge.send("send_turn", {"text": "hello"}, "op-1")
        # The submit is active but its agent run has not been observed
        # starting yet: refusing here is proven before any native write.
        with pytest.raises(RuntimeCommandNotSent,
                           match="no started pi agent run") as exc:
            await bridge.send("steer", {"text": "too early"}, "steer-early")
        assert exc.value.code == "STALE_TURN"
        assert [command.verb for command in connector.sent] == ["send_turn"]
        stream = bridge.events()
        assert (await anext(stream)).native_type == "agent_start"
        await bridge.send("steer", {"text": "redirect"}, "steer-1")
        assert connector.sent[-1].verb == "steer"
        assert connector.sent[-1].payload == {"text": "redirect"}
        terminal = await anext(stream)
        assert terminal.native_type == "agent_settled"
        assert terminal.operation_id == "op-1"
        assert not bridge.active_turn()
        with pytest.raises(RuntimeCommandNotSent, match="no active turn"):
            await bridge.send("steer", {"text": "late"}, "steer-late")
        await bridge.close()

    asyncio.run(run())


@pytest.mark.parametrize("stale_turn_id", ["native-turn-1", None])
def test_codex_old_or_uncorrelated_terminal_cannot_settle_new_turn(stale_turn_id):
    class TurnConnector(FakeCopiedConnector):
        def events(self):
            for kind, native_type, turn_id, phase in (
                    ("turn_started", "turn/started", "native-turn-1", "started"),
                    ("turn_completed", "turn/completed", "native-turn-1", "terminal"),
                    ("turn_started", "turn/started", "native-turn-2", "started"),
                    ("turn_completed", "turn/completed", stale_turn_id, "terminal")):
                yield HarnessEvent(
                    "native-session", "codex", kind, native_type,
                    "2026-09-25T00:00:00Z", {}, turn_id=turn_id,
                    delivery_phase=phase, delivery_outcome=(
                        "success" if phase == "terminal" else None))

    async def run():
        connector = TurnConnector()
        harness = HarnessSession(
            "native-session", "codex", "agent", "STARTING",
            HarnessCapabilities(False, "IMMEDIATE", False, False, True),
            "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(
            connector, harness, session_id="public-session",
            stream_epoch="epoch", context=context())
        await bridge.send("send_turn", {"text": "first"}, "op-1")
        stream = bridge.events()
        assert (await anext(stream)).payload["turn_id"] == "native-turn-1"
        first_terminal = await anext(stream)
        assert first_terminal.operation_id == "op-1"
        assert not bridge.active_turn()

        await bridge.send("send_turn", {"text": "second"}, "op-2")
        assert (await anext(stream)).payload["turn_id"] == "native-turn-2"
        with pytest.raises(CoreError, match="EVENT_OPERATION_MISMATCH") as denied:
            await anext(stream)
        assert denied.value.possible_effect
        assert bridge.active_turn()
        assert bridge._active_turn_id == "native-turn-2"
        assert bridge._last_outcome is None

    asyncio.run(run())


def test_codex_replayed_started_turn_cannot_claim_new_operation():
    class ReplayedStart(FakeCopiedConnector):
        def events(self):
            for kind, turn_id, phase in (
                    ("turn_started", "native-turn-1", "started"),
                    ("turn_completed", "native-turn-1", "terminal"),
                    ("turn_started", "native-turn-1", "started")):
                yield HarnessEvent(
                    "native-session", "codex", kind,
                    "turn/started" if kind == "turn_started" else "turn/completed",
                    "2026-09-25T00:00:00Z", {}, turn_id=turn_id,
                    delivery_phase=phase)

    async def run():
        connector = ReplayedStart()
        harness = HarnessSession(
            "native-session", "codex", "agent", "STARTING",
            HarnessCapabilities(False, "IMMEDIATE", False, False, True),
            "2026-09-25T00:00:00Z")
        bridge = CopiedAdapterSession(
            connector, harness, session_id="public-session",
            stream_epoch="epoch", context=context())
        await bridge.send("send_turn", {"text": "first"}, "op-1")
        stream = bridge.events()
        await anext(stream)
        assert (await anext(stream)).operation_id == "op-1"
        await bridge.send("send_turn", {"text": "second"}, "op-2")
        with pytest.raises(CoreError, match="EVENT_OPERATION_MISMATCH"):
            await anext(stream)
        assert bridge.active_turn()
        assert bridge._active_turn_id is None

    asyncio.run(run())


def test_codex_stale_terminal_keeps_new_runtime_receipt_unsettled(tmp_path):
    class QueuedTurns(FakeCopiedConnector):
        def __init__(self):
            super().__init__()
            self.pending = queue.Queue()

        def events(self):
            while True:
                event = self.pending.get()
                if event is None:
                    return
                yield event

        def close(self):
            super().close()
            self.pending.put(None)

    class Factory:
        def __init__(self, connector, authority):
            self.connector = connector
            self.authority = authority

        async def open(self, prepared, session_id, context, *, stream_epoch):
            harness = HarnessSession(
                "native-session", "codex", "agent", "STARTING",
                HarnessCapabilities(False, "IMMEDIATE", False, False, True),
                "2026-09-25T00:00:00Z")
            return CopiedAdapterSession(
                self.connector, harness, session_id=session_id,
                stream_epoch=stream_epoch, context=self.authority)

    def native_event(kind, turn_id, phase):
        return HarnessEvent(
            "native-session", "codex", kind,
            "turn/started" if kind == "turn_started" else "turn/completed",
            "2026-09-25T00:00:00Z", {}, turn_id=turn_id,
            delivery_phase=phase,
            delivery_outcome="success" if phase == "terminal" else None)

    async def run():
        binary = tmp_path / "synthetic-codex"
        binary.write_bytes(b"synthetic")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), fingerprint(binary),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "stale-terminal.db")
        authority = context()
        authority = ExecutionContext(
            authority.server_id, authority.executor_id, authority.binding_id,
            authority.agent_id, authority.workspace_id,
            authority.authorization_revision, authority.configuration_revision,
            authority.connection_generation, authority.lease_deadline_monotonic,
            authority.allowed_actions | {"runtime.close"})
        connector = QueuedTurns()
        runtime = LocalRuntimeCore(
            journal, Factory(connector, authority),
            candidates={"codex_app_server": candidate},
            workspace_roots={"ws": str(tmp_path)})
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            await runtime.submit(TurnOperation("first", "session", "one"), authority)
            connector.pending.put(native_event("turn_started", "turn-1", "started"))
            connector.pending.put(native_event("turn_completed", "turn-1", "terminal"))

            async def first_settled():
                while True:
                    receipt = await journal.get_receipt(
                        OperationKey("srv", "exe", "first"))
                    if receipt is not None and receipt.stage == "SUCCEEDED":
                        return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(first_settled(), timeout=3)
            await runtime.submit(TurnOperation("second", "session", "two"), authority)
            connector.pending.put(native_event("turn_started", "turn-2", "started"))
            connector.pending.put(native_event("turn_completed", "turn-1", "terminal"))

            async def pump_faulted():
                while not runtime._sessions[SessionKey("srv", "exe", "session")].faulted:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(pump_faulted(), timeout=3)
            second = await journal.get_receipt(OperationKey("srv", "exe", "second"))
            assert second.stage == "SUBMITTED" and second.possible_effect
            assert not second.stage == "SUCCEEDED"
            await runtime.shutdown(ShutdownPolicy(0.01, 0.01))
        finally:
            connector.close()
            journal.close()

    asyncio.run(run())


def test_real_factory_fails_closed_before_resolving_secrets():
    async def run():
        called = False

        async def environment(_prepared):
            nonlocal called
            called = True
            return {}

        candidate = InstallationCandidate("codex_app_server", "C:/codex.exe",
                                          "sha256:abc", "explicit", "selected",
                                          version="0.156.1")
        intent = LaunchIntent("agent", "ws", "codex_app_server")
        prepared = PreparedLaunch(intent, candidate, ("C:/codex.exe", "app-server"),
                                  "C:/workspace", "C:/workspace", "root", "profile", ())
        with pytest.raises(CoreError, match="NATIVE_VERSION_UNQUALIFIED") as denied:
            await CopiedAdapterFactory(environment).open(prepared, "session",
                                                         context(), stream_epoch="epoch")
        assert denied.value.retry_safe and not denied.value.possible_effect
        assert not called

    asyncio.run(run())


def test_factory_passes_only_preapproved_capability_env_to_adapter(monkeypatch):
    import nexus_connector_core.native.runtime_bridge as bridge_module
    import nexus_connector_core.native.adapters.codex as codex_module

    ref = "mcp-cap:binding-1"
    template = harness_http_template(
        "codex_app_server", "https://nexus.example.test/mcp", ref,
        entry_name="okto-nexus", harness_is_local=False,
        approved_origins={"https://nexus.example.test"}, format_qualified=True)
    candidate = InstallationCandidate("codex_app_server", "C:/codex.exe",
                                      "sha256:abc", "explicit", "selected",
                                      version="synthetic")
    intent = LaunchIntent("agent", "ws", "codex_app_server", auth_refs=(ref,))
    prepared = PreparedLaunch(intent, candidate, ("C:/codex.exe", "app-server"),
                              "C:/workspace", "C:/workspace", "root", "profile", (ref,))
    seen = []

    class StubCodex:
        def __init__(self, *, command, cwd, env):
            seen.append(legacy_child_environment(env))
            self.native_approvals_enabled = False

        def start(self, *, owning_agent_id):
            return HarnessSession("native-session", "codex", owning_agent_id,
                                  "STARTING", HarnessCapabilities(False, None,
                                                                  False, False, True),
                                  "2026-09-25T00:00:00Z")

        def close(self):
            pass

    monkeypatch.setattr(bridge_module, "qualified_build",
                         lambda *args, **kwargs: True)
    monkeypatch.setattr(codex_module, "CodexAppServerConnector", StubCodex)

    async def run():
        async def approved_env(_prepared):
            return {template.bearer_env_name: "scoped-token"}

        session = await CopiedAdapterFactory(approved_env).open(
            prepared, "session", context(), stream_epoch="epoch")
        assert seen[-1][template.bearer_env_name] == "scoped-token"
        assert "NEXUS_OPERATOR_KEY" not in seen[-1]
        assert session._redactor.clean("scoped-token") == "[REDACTED]"

        async def unapproved_env(_prepared):
            return {"NEXUS_OPERATOR_KEY": "admin-secret"}

        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await CopiedAdapterFactory(unapproved_env).open(
                prepared, "session", context(), stream_epoch="epoch")
        assert len(seen) == 1

        async def wrong_ref_env(_prepared):
            return {harness_http_template(
                "codex_app_server", "https://nexus.example.test/mcp",
                "mcp-cap:another", entry_name="okto-nexus", harness_is_local=False,
                approved_origins={"https://nexus.example.test"},
                format_qualified=True).bearer_env_name: "scoped-token"}

        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await CopiedAdapterFactory(wrong_ref_env).open(
                prepared, "session", context(), stream_epoch="epoch")
        assert len(seen) == 1

        assert session._connector.native_approvals_enabled is False
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await CopiedAdapterFactory(
                approved_env, native_approvals_enabled=True).open(
                    prepared, "session", context(), stream_epoch="epoch")
        approval_context = context()
        approval_context = ExecutionContext(
            approval_context.server_id, approval_context.executor_id,
            approval_context.binding_id, approval_context.agent_id,
            approval_context.workspace_id,
            approval_context.authorization_revision,
            approval_context.configuration_revision,
            approval_context.connection_generation,
            approval_context.lease_deadline_monotonic,
            approval_context.allowed_actions | {"approval.decide",
                                                "input.provide"})
        opted_in = await CopiedAdapterFactory(
            approved_env, native_approvals_enabled=True).open(
                prepared, "session", approval_context, stream_epoch="epoch")
        assert opted_in._connector.native_approvals_enabled is True
        with pytest.raises(ValueError, match="native_approvals_enabled"):
            CopiedAdapterFactory(approved_env, native_approvals_enabled=1)

    asyncio.run(run())


def test_factory_pi_native_action_launch_is_scoped_and_adds_local_extension(monkeypatch):
    import nexus_connector_core.native.runtime_bridge as bridge_module
    import nexus_connector_core.native.adapters.pi as pi_module

    reference = "native-cap:session"
    candidate = InstallationCandidate("pi_rpc", "C:/pi.exe", "sha256:abc",
                                      "explicit", "selected", version="synthetic")
    intent = LaunchIntent("agent", "ws", "pi_rpc", auth_refs=(reference,))
    prepared = PreparedLaunch(intent, candidate, ("C:/pi.exe", "--mode", "rpc"),
                              "C:/workspace", "C:/workspace", "root", "profile",
                              (reference,))
    observed = []

    class StubPi:
        def __init__(self, *, command, cwd, env, native_action):
            observed.append((command, cwd, env, native_action))

        def start(self, *, owning_agent_id):
            return HarnessSession("native-session", "pi", owning_agent_id,
                                  "STARTING", HarnessCapabilities(False, None,
                                                                  False, False, True),
                                  "2026-09-25T00:00:00Z")

        def close(self):
            pass

    monkeypatch.setattr(bridge_module, "qualified_build",
                         lambda *args, **kwargs: True)
    monkeypatch.setattr(pi_module, "PiRpcConnector", StubPi)

    async def run():
        async def approved_env(_prepared):
            return {}

        async def config(_prepared, session_id, _context):
            return PiNativeActionLaunch(8765, reference, session_id)

        await CopiedAdapterFactory(approved_env, pi_native_action=config).open(
            prepared, "session", context(), stream_epoch="epoch")
        assert observed[-1][3].session_id == "session"

        async def wrong(_prepared, _session_id, _context):
            return PiNativeActionLaunch(8765, reference, "other")

        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await CopiedAdapterFactory(approved_env, pi_native_action=wrong).open(
                prepared, "session", context(), stream_epoch="epoch")
        assert len(observed) == 1

    asyncio.run(run())

    native = PiNativeActionLaunch(8765, reference, "session")
    connector = PiRpcConnector(command=("pi", "--mode", "rpc"), native_action=native)
    argv = connector._build_argv("native-session")
    assert argv[-2:] == ["--extension", str(pi_extension_path())]
    child_env = legacy_child_environment({}, native_action=native)
    assert child_env["NEXUS_NATIVE_ACTION_PORT"] == "8765"
    assert child_env["NEXUS_NATIVE_CAPABILITY_REF"] == reference
    with pytest.raises(Exception):
        legacy_child_environment({"NEXUS_NATIVE_CAPABILITY_REF": "evil"})


def test_copied_pi_peer_through_public_async_runtime(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"

    class FixtureFactory:
        async def open(self, prepared, session_id, context, *, stream_epoch):
            connector = PiRpcConnector(
                command=(sys.executable, str(peer), str(tmp_path / "pi-log.jsonl")),
                version_command=(sys.executable, "-c", "print('0.85.1')"),
                cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
            native_session = await asyncio.to_thread(connector.start,
                                                     owning_agent_id=context.agent_id)
            return CopiedAdapterSession(connector, native_session,
                                        session_id=session_id,
                                        stream_epoch=stream_epoch, context=context)

    async def run():
        candidate = InstallationCandidate("pi_rpc", sys.executable,
                                          fingerprint(Path(sys.executable)),
                                          "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(journal, FixtureFactory(),
                                   candidates={"pi_rpc": candidate},
                                   workspace_roots={"ws": str(tmp_path)})
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "pi_rpc"),
                                         context())
        await runtime.open(OpenOperation("open", "public-session", "epoch", prepared),
                           context())
        await runtime.submit(TurnOperation("turn", "public-session", "hello"),
                             context())
        cursor = EventCursor("srv", "exe", "public-session", "epoch")

        async def completed():
            seen = []
            async for event in runtime.events(cursor):
                seen.append(event)
                if event.native_type == "agent_settled":
                    return seen

        seen = await asyncio.wait_for(completed(), timeout=10)
        assert any(item.native_type == "turn_end" for item in seen)
        assert seen[-1].category == "turn_state"
        assert seen[-1].sequence == await journal.contiguous_watermark(cursor)
        assert seen[-1].operation_id == "turn"
        assert seen[-1].payload["delivery_phase"] == "terminal"
        assert (await journal.get_receipt(OperationKey("srv", "exe", "turn"))).stage == "SUCCEEDED"
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_pi_rejected_prompt_never_gets_submitted_receipt(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"

    class FixtureFactory:
        async def open(self, prepared, session_id, authority, *, stream_epoch):
            connector = PiRpcConnector(
                command=(sys.executable, str(peer), str(tmp_path / "pi-log.jsonl")),
                version_command=(sys.executable, "-c", "print('0.85.1')"),
                cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
            native = await asyncio.to_thread(
                connector.start, owning_agent_id=authority.agent_id)
            return CopiedAdapterSession(
                connector, native, session_id=session_id,
                stream_epoch=stream_epoch, context=authority)

    async def run():
        candidate = InstallationCandidate(
            "pi_rpc", sys.executable, fingerprint(Path(sys.executable)),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(
            journal, FixtureFactory(), candidates={"pi_rpc": candidate},
            workspace_roots={"ws": str(tmp_path)})
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "pi_rpc"), context())
            await runtime.open(
                OpenOperation("open", "public-session", "epoch", prepared),
                context())
            with pytest.raises(NativeAdapterError, match="rejected the prompt") as excinfo:
                await runtime.submit(
                    TurnOperation("rejected", "public-session", "TRIGGER_ERROR"),
                    context())
            assert excinfo.value.details.get("not_sent") is not True
            receipt = await journal.get_receipt(
                OperationKey("srv", "exe", "rejected"))
            assert receipt.stage == "OUTCOME_UNKNOWN"
            assert receipt.possible_effect
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_pi_rejected_abort_never_gets_submitted_receipt(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"

    class FixtureFactory:
        async def open(self, prepared, session_id, authority, *, stream_epoch):
            connector = PiRpcConnector(
                command=(sys.executable, str(peer), str(tmp_path / "pi-log.jsonl")),
                version_command=(sys.executable, "-c", "print('0.85.1')"),
                cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
            native = await asyncio.to_thread(
                connector.start, owning_agent_id=authority.agent_id)
            return CopiedAdapterSession(
                connector, native, session_id=session_id,
                stream_epoch=stream_epoch, context=authority)

    async def run():
        candidate = InstallationCandidate(
            "pi_rpc", sys.executable, fingerprint(Path(sys.executable)),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(
            journal, FixtureFactory(), candidates={"pi_rpc": candidate},
            workspace_roots={"ws": str(tmp_path)})
        authority = replace(context(), allowed_actions=frozenset({
            "runtime.open", "turn.submit", "turn.interrupt"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "pi_rpc"), authority)
            await runtime.open(
                OpenOperation("open", "public-session", "epoch", prepared),
                authority)
            await runtime.submit(
                TurnOperation("turn", "public-session",
                              "TRIGGER_HOLD_FOR_ABORT TRIGGER_REJECT_ABORT"),
                authority)
            with pytest.raises(NativeAdapterError, match="rejected the abort") as excinfo:
                await runtime.control(
                    ControlOperation("rejected-abort", "public-session",
                                     "interrupt"), authority)
            assert excinfo.value.details.get("not_sent") is not True
            receipt = await journal.get_receipt(
                OperationKey("srv", "exe", "rejected-abort"))
            assert receipt.stage == "OUTCOME_UNKNOWN"
            assert receipt.possible_effect
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_pi_stale_idless_terminal_cannot_complete_new_public_operation(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"

    class FixtureFactory:
        async def open(self, prepared, session_id, authority, *, stream_epoch):
            connector = PiRpcConnector(
                command=(sys.executable, str(peer), str(tmp_path / "pi-log.jsonl")),
                version_command=(sys.executable, "-c", "print('0.85.1')"),
                cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
            native = await asyncio.to_thread(
                connector.start, owning_agent_id=authority.agent_id)
            return CopiedAdapterSession(
                connector, native, session_id=session_id,
                stream_epoch=stream_epoch, context=authority)

    async def run():
        candidate = InstallationCandidate(
            "pi_rpc", sys.executable, fingerprint(Path(sys.executable)),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(
            journal, FixtureFactory(), candidates={"pi_rpc": candidate},
            workspace_roots={"ws": str(tmp_path)})
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "pi_rpc"), context())
            await runtime.open(
                OpenOperation("open", "public-session", "epoch", prepared),
                context())
            await runtime.submit(
                TurnOperation("turn", "public-session",
                              "TRIGGER_STALE_SETTLED_BEFORE_START"), context())

            async def pump_failed():
                while True:
                    async for event in runtime.events(EventCursor(
                            "srv", "exe", "public-session", "epoch")):
                        if event.native_type == "core.event_pump_failed":
                            return event
                    await asyncio.sleep(0.01)

            error = await asyncio.wait_for(pump_failed(), timeout=5)
            assert error.payload["code"] == "EVENT_STREAM_UNAVAILABLE"
            receipt = await journal.get_receipt(OperationKey("srv", "exe", "turn"))
            assert receipt.stage == "SUBMITTED" and receipt.possible_effect
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_pi_public_idless_steer_settles_active_turn(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"

    class FixtureFactory:
        async def open(self, prepared, session_id, authority, *, stream_epoch):
            connector = PiRpcConnector(
                command=(sys.executable, str(peer), str(tmp_path / "pi-log.jsonl")),
                version_command=(sys.executable, "-c", "print('0.85.1')"),
                cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
            native = await asyncio.to_thread(
                connector.start, owning_agent_id=authority.agent_id)
            return CopiedAdapterSession(
                connector, native, session_id=session_id,
                stream_epoch=stream_epoch, context=authority)

    async def run():
        candidate = InstallationCandidate(
            "pi_rpc", sys.executable, fingerprint(Path(sys.executable)),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(
            journal, FixtureFactory(), candidates={"pi_rpc": candidate},
            workspace_roots={"ws": str(tmp_path)})
        authority = replace(context(), allowed_actions=frozenset({
            "runtime.open", "turn.submit", "turn.steer", "turn.interrupt"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "pi_rpc"), authority)
            await runtime.open(
                OpenOperation("open", "public-session", "epoch", prepared),
                authority)
            await runtime.submit(
                TurnOperation("turn", "public-session", "TRIGGER_HOLD_FOR_STEER"),
                authority)

            async def native_type(native):
                async for event in runtime.events(EventCursor(
                        "srv", "exe", "public-session", "epoch")):
                    if event.native_type == native:
                        return event

            await asyncio.wait_for(native_type("agent_start"), timeout=5)
            steer = await runtime.control(
                ControlOperation("steer", "public-session", "steer",
                                 "redirect to tests"), authority)
            assert steer.stage == "SUBMITTED" and steer.possible_effect
            queued = await asyncio.wait_for(native_type("queue_update"),
                                            timeout=5)
            assert queued.payload.get("steering") == ["redirect to tests"]
            terminal = await asyncio.wait_for(native_type("agent_settled"),
                                              timeout=10)
            assert terminal.operation_id == "turn"
            assert terminal.payload.get("delivery_phase") == "terminal"
            receipt = await journal.get_receipt(OperationKey("srv", "exe", "turn"))
            assert receipt.stage == "SUCCEEDED"
            # The steer command's own receipt stays at accepted-possible-
            # effect: only the active submit's terminal settles, and the
            # steered content is part of that same turn.
            steer_receipt = await journal.get_receipt(
                OperationKey("srv", "exe", "steer"))
            assert steer_receipt.stage == "SUBMITTED"
            # A Pi steer naming a native turn ID is refused before admission.
            with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
                await runtime.control(
                    ControlOperation("native-target", "public-session", "steer",
                                     "x", "native-turn-1"), authority)
            assert (await journal.get_receipt(
                OperationKey("srv", "exe", "native-target"))) is None
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_pi_public_interrupt_settles_and_allows_follow_up_submit(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"

    class FixtureFactory:
        async def open(self, prepared, session_id, authority, *, stream_epoch):
            connector = PiRpcConnector(
                command=(sys.executable, str(peer), str(tmp_path / "pi-log.jsonl")),
                version_command=(sys.executable, "-c", "print('0.85.1')"),
                cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
            native = await asyncio.to_thread(
                connector.start, owning_agent_id=authority.agent_id)
            return CopiedAdapterSession(
                connector, native, session_id=session_id,
                stream_epoch=stream_epoch, context=authority)

    async def run():
        candidate = InstallationCandidate(
            "pi_rpc", sys.executable, fingerprint(Path(sys.executable)),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(
            journal, FixtureFactory(), candidates={"pi_rpc": candidate},
            workspace_roots={"ws": str(tmp_path)})
        authority = replace(context(), allowed_actions=frozenset({
            "runtime.open", "turn.submit", "turn.steer", "turn.interrupt"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "pi_rpc"), authority)
            await runtime.open(
                OpenOperation("open", "public-session", "epoch", prepared),
                authority)
            await runtime.submit(
                TurnOperation("turn-1", "public-session", "TRIGGER_HOLD_FOR_ABORT"),
                authority)

            async def wait_terminal(operation_id):
                async for event in runtime.events(EventCursor(
                        "srv", "exe", "public-session", "epoch")):
                    if (event.native_type == "agent_settled" and
                            event.payload.get("delivery_phase") == "terminal" and
                            event.operation_id == operation_id):
                        return event

            async def wait_started():
                async for event in runtime.events(EventCursor(
                        "srv", "exe", "public-session", "epoch")):
                    if event.native_type == "agent_start":
                        return event

            await asyncio.wait_for(wait_started(), timeout=5)
            interrupt = await runtime.control(
                ControlOperation("interrupt-1", "public-session", "interrupt"),
                authority)
            assert interrupt.stage == "SUBMITTED" and interrupt.possible_effect
            terminal = await asyncio.wait_for(wait_terminal("turn-1"), timeout=10)
            assert terminal.operation_id == "turn-1"
            receipt = await journal.get_receipt(
                OperationKey("srv", "exe", "turn-1"))
            # The aborted peer turn ends with stopReason "error", which the
            # reducer maps to a FAILED terminal - never a silent success.
            assert receipt.stage == "FAILED"
            # Follow-up after the real settle is a new submit, not a replay:
            # the aborted turn no longer occupies the session's turn slot.
            follow_up = await runtime.submit(
                TurnOperation("turn-2", "public-session", "follow up"),
                authority)
            assert follow_up.stage == "SUBMITTED"
            terminal_two = await asyncio.wait_for(wait_terminal("turn-2"),
                                                  timeout=10)
            assert terminal_two.operation_id == "turn-2"
            second = await journal.get_receipt(
                OperationKey("srv", "exe", "turn-2"))
            assert second.stage == "SUCCEEDED"
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter_id", ["codex_app_server", "claude_stream"])
def test_copied_peer_terminal_reduces_public_receipt(tmp_path, adapter_id):
    fixture_dir = Path(__file__).parent / "fixtures"

    class FixtureFactory:
        async def open(self, prepared, session_id, context, *, stream_epoch):
            if adapter_id == "codex_app_server":
                connector = CodexAppServerConnector(
                    command=(sys.executable,
                             str(fixture_dir / "codex_app_server_peer.py"),
                             str(tmp_path / "codex-log.jsonl")),
                    cwd=str(tmp_path), handshake_timeout_s=5)
            else:
                peer = fixture_dir / "claude_stream_peer.py"
                connector = ClaudeCodeStreamConnector(
                    binary=sys.executable,
                    argv=("-u", "-c", peer.read_text(encoding="utf-8")),
                    cwd=str(tmp_path), env={"FAKE_CC_SCENARIO": "basic"})
            native_session = await asyncio.to_thread(connector.start,
                                                     owning_agent_id=context.agent_id)
            return CopiedAdapterSession(connector, native_session,
                                        session_id=session_id,
                                        stream_epoch=stream_epoch, context=context)

    async def run():
        candidate = InstallationCandidate(adapter_id, sys.executable,
                                          fingerprint(Path(sys.executable)),
                                          "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(journal, FixtureFactory(),
                                   candidates={adapter_id: candidate},
                                   workspace_roots={"ws": str(tmp_path)})
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", adapter_id),
                                         context())
        await runtime.open(OpenOperation("open", "public-session", "epoch", prepared),
                           context())
        await runtime.submit(TurnOperation("turn", "public-session", "hello"),
                             context())

        async def terminal():
            async for item in runtime.events(EventCursor("srv", "exe",
                                                        "public-session", "epoch")):
                if item.payload.get("delivery_phase") == "terminal":
                    return item

        item = await asyncio.wait_for(terminal(), timeout=10)
        assert item.operation_id == "turn"
        assert item.payload["delivery_outcome"] == "success"
        assert (await journal.get_receipt(OperationKey("srv", "exe", "turn"))).stage == "SUCCEEDED"
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())
