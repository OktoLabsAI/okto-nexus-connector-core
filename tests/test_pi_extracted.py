"""Run the extracted Pi connector against the preserved Nexus synthetic peer."""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from nexus_connector_core.native.adapter_types import STATUS_RUNNING, HarnessCommand, HarnessSession, NativeAdapterError
from nexus_connector_core.native.adapters.pi import PiRpcConnector, _PiTransport


def test_pi_presentation_state_requires_the_exact_correlated_owner():
    connector = PiRpcConnector(command=("pi", "--mode", "rpc"))
    session = HarnessSession("owned", "pi", "agent", STATUS_RUNNING, connector.capabilities, "start")
    connector._session_id = session.session_id
    connector._compatibility_report = {"native_version": "0.87.1"}
    transport = Mock(spec_set=["is_alive", "request", "_response_ids_required"])
    connector._transport = transport
    transport.is_alive.return_value = True
    transport._response_ids_required = True
    state = {"sessionId": "owned", "isStreaming": True, "isCompacting": False,
             "pendingMessageCount": 2, "sessionFile": "private", "model": "private"}
    transport.request.return_value = {"success": True, "data": state}

    assert connector.read_owned_pi_state(session) == {
        "native_session_id": "owned", "is_streaming": True,
        "is_compacting": False, "pending_message_count": 2,
    }
    transport.request.assert_called_once_with("get_state", {}, timeout_s=5.0)
    for change in ({"sessionId": "sibling"}, {"isCompacting": None}, {"isStreaming": 1},
                   {"pendingMessageCount": True}, {"pendingMessageCount": -1},
                   {"pendingMessageCount": 2**31}):
        transport.request.return_value = {"success": True, "data": state | change}
        with pytest.raises(NativeAdapterError, match="selected session"):
            connector.read_owned_pi_state(session)

    transport.request.return_value = {"success": True, "data": state}
    transport.is_alive.side_effect = [True, False]
    with pytest.raises(NativeAdapterError, match="owner changed"):
        connector.read_owned_pi_state(session)
    transport.is_alive.side_effect = None
    transport.request.reset_mock()
    transport._response_ids_required = False
    with pytest.raises(NativeAdapterError, match="state is unavailable"):
        connector.read_owned_pi_state(session)
    transport._response_ids_required = True
    connector._compatibility_report["native_version"] = "0.85.1"
    with pytest.raises(NativeAdapterError, match="state is unavailable"):
        connector.read_owned_pi_state(session)
    transport.request.assert_not_called()


def test_pi_node_cli_default_version_command_probes_package():
    connector = PiRpcConnector(command=("node.exe", "C:/pi/dist/bundle/cli.js",
                                        "--mode", "rpc"))
    assert connector._version_command == ["node.exe", "C:/pi/dist/bundle/cli.js",
                                          "--version"]
    direct = PiRpcConnector(command=("pi", "--mode", "rpc"))
    assert direct._version_command == ["pi", "--version"]


@pytest.mark.parametrize("verb", ["steer", "abort"])
def test_pi_rejected_control_fails_after_protocol_write(tmp_path, verb):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"
    connector = PiRpcConnector(
        command=(sys.executable, str(peer), str(tmp_path / "pi-log.jsonl")),
        version_command=(sys.executable, "-c", "print('0.85.1')"),
        cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
    try:
        session = connector.start(owning_agent_id="test-agent")
        marker = ("TRIGGER_HOLD_FOR_STEER" if verb == "steer" else
                  "TRIGGER_HOLD_FOR_ABORT TRIGGER_REJECT_ABORT")
        connector.send(session, HarnessCommand(session.session_id, "send_turn",
                                               {"text": marker}))
        payload = {"text": "TRIGGER_REJECT_STEER"} if verb == "steer" else {}
        with pytest.raises(NativeAdapterError, match=f"rejected the {verb}") as excinfo:
            connector.send(session, HarnessCommand(
                session.session_id, "interrupt" if verb == "abort" else verb,
                payload))
        assert excinfo.value.details.get("not_sent") is not True
    finally:
        connector.close()


def test_pi_extracted_multi_event_turn(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"
    log = tmp_path / "pi-log.jsonl"
    connector = PiRpcConnector(
        command=(sys.executable, str(peer), str(log)),
        version_command=(sys.executable, "-c", "print('0.85.1')"),
        cwd=str(tmp_path), handshake_timeout_s=5, command_timeout_s=5)
    seen = []
    done = threading.Event()

    def consume():
        for event in connector.events():
            seen.append(event)
            if event.native_event == "agent_settled":
                done.set()
                break

    try:
        session = connector.start(owning_agent_id="test-agent")
        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        connector.send(session, HarnessCommand(session.session_id, "send_turn",
                                               {"text": "hello"}))
        assert done.wait(timeout=8), [event.native_event for event in seen]
        native = [event.native_event for event in seen
                  if event.native_event != "extension_ui_request"]
        assert native == ["agent_start", "turn_start", "message_start",
                          "message_end", "message_start", "message_update",
                          "message_end", "turn_end", "agent_end", "agent_settled"]
        assert next(e for e in seen if e.native_event == "turn_end").kind != "turn_completed"
        assert next(e for e in seen if e.native_event == "agent_settled").kind == "turn_completed"
        assert session.compatibility_report["native_version"] == "0.85.1"
    finally:
        connector.close()


def test_pi_id_echo_correlates_out_of_order_same_verb_and_late_reply(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "pi_rpc_ids_peer.py"
    unmatched = []
    transport = _PiTransport(
        (sys.executable, str(peer)), cwd=str(tmp_path), env={},
        on_push_event=lambda _: None,
        on_unmatched_response=unmatched.append,
        on_child_exit=lambda *_: None,
        on_malformed_line=lambda *_: None,
        on_line_processing_error=lambda *_: None,
        on_reader_exit=lambda: None,
    )
    transport._response_ids_required = True
    transport.start()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(transport.request, "get_state",
                                    {"tag": "first"}, timeout_s=3)
            second = executor.submit(transport.request, "get_state",
                                     {"tag": "second"}, timeout_s=3)
            assert first.result(timeout=4)["data"]["tag"] == "first"
            assert second.result(timeout=4)["data"]["tag"] == "second"
        with pytest.raises(Exception, match="did not answer"):
            transport.request("get_state", {"tag": "late"}, timeout_s=0.05)
        assert transport.request("get_state", {"tag": "fast"},
                                 timeout_s=3)["data"]["tag"] == "fast"
        deadline = time.monotonic() + 3
        while not unmatched and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(unmatched) == 1
        assert unmatched[0]["data"]["tag"] == "late"
        assert not transport._response_correlation_lost
    finally:
        transport.close()


def test_pi_0871_readiness_requires_echoed_id(tmp_path):
    ids_peer = Path(__file__).parent / "fixtures" / "pi_rpc_ids_peer.py"
    connector = PiRpcConnector(
        command=(sys.executable, str(ids_peer)),
        version_command=(sys.executable, "-c", "print('0.87.1')"),
        cwd=str(tmp_path), handshake_timeout_s=2)
    try:
        session = connector.start(owning_agent_id="agent")
        assert session.compatibility_report["native_version"] == "0.87.1"
        assert connector._transport._response_ids_required
    finally:
        connector.close()

    old_peer = Path(__file__).parent / "fixtures" / "pi_rpc_peer.py"
    missing_echo = PiRpcConnector(
        command=(sys.executable, str(old_peer), str(tmp_path / "log.jsonl")),
        version_command=(sys.executable, "-c", "print('0.87.1')"),
        cwd=str(tmp_path), handshake_timeout_s=0.2)
    try:
        with pytest.raises(Exception, match="did not answer"):
            missing_echo.start(owning_agent_id="agent")
    finally:
        missing_echo.close()
