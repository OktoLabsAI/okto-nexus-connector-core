"""Extracted Claude stream adapter against the preserved Nexus peer."""

import sys
import threading
from pathlib import Path

import pytest

from nexus_connector_core.native.adapter_types import HarnessCommand, RuntimeCommandNotSent
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector


def test_claude_extracted_stream_result(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "claude_stream_peer.py"
    connector = ClaudeCodeStreamConnector(
        binary=sys.executable, argv=("-u", "-c", peer.read_text(encoding="utf-8")),
        cwd=str(tmp_path), env={"FAKE_CC_SCENARIO": "basic"})
    seen = []
    done = threading.Event()

    def consume():
        for event in connector.events():
            seen.append(event)
            if event.kind == "turn_completed":
                done.set()
                break

    try:
        session = connector.start(owning_agent_id="test-agent")
        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        connector.send(session, HarnessCommand(session.session_id, "send_turn",
                                               {"content": "hello"}))
        assert done.wait(timeout=8), [event.native_event for event in seen]
        assert any(event.kind == "output_delta" for event in seen)
        assert seen[-1].kind == "turn_completed"
    finally:
        connector.close()


@pytest.mark.parametrize("verb", ["interrupt", "steer"])
def test_requesting_phase_control_rejected_before_native_write(tmp_path, verb):
    peer = Path(__file__).parent / "fixtures" / "claude_stream_peer.py"
    connector = ClaudeCodeStreamConnector(
        binary=sys.executable, argv=("-u", "-c", peer.read_text(encoding="utf-8")),
        cwd=str(tmp_path), env={"FAKE_CC_SCENARIO": "slow_start"})
    try:
        session = connector.start(owning_agent_id="test-agent")
        connector.send(session, HarnessCommand(session.session_id, "send_turn",
                                               {"content": "first"}))
        assert not connector._turn_generating.is_set()
        control = HarnessCommand(session.session_id, verb,
                                 {"content": "replacement"} if verb == "steer" else {})
        with pytest.raises(RuntimeCommandNotSent, match="requesting"):
            connector.send(session, control)
        assert list(connector._pending_turns) == [False]
        assert connector._interrupt_request_counter == 0
        assert connector._pending_admissions == 0
        events = []
        for event in connector.events():
            events.append(event)
            if event.kind == "turn_completed":
                break
        assert events[-1].kind == "turn_completed"
        assert not any(event.native_event == "control_response" for event in events)
    finally:
        connector.close()
