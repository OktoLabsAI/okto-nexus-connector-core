"""Adapter refusals classified as definitely before native protocol writes."""

import os

import pytest

from nexus_connector_core.native.adapter_types import (
    ErrorCode,
    HarnessCommand,
    HarnessSession,
    NativeAdapterError,
)
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.adapters.pi import PiRpcConnector


def _session(connector, connector_type):
    return HarnessSession(
        "native-session", connector_type, "agent", "STARTING",
        connector.capabilities, "2026-09-25T00:00:00Z",
    )


@pytest.mark.parametrize("connector_type,connector_class,payload_key", [
    ("pi", PiRpcConnector, "text"),
    ("claude_code", ClaudeCodeStreamConnector, "content"),
])
def test_invalid_content_is_prewrite_without_echoing_payload(
    connector_type, connector_class, payload_key,
):
    connector = connector_class()
    command = HarnessCommand("native-session", "send_turn", {payload_key: 123, "secret": "private"})
    with pytest.raises(NativeAdapterError) as failure:
        if connector_type == "pi":
            connector._extract_text(command)
        else:
            connector._require_content(command)
    assert failure.value.code == ErrorCode.VALIDATION_ERROR
    assert failure.value.details["not_sent"] is True
    assert "payload" not in failure.value.details


def test_pi_refuses_missing_session_and_unsettled_turn_before_transport():
    connector = PiRpcConnector()
    session = _session(connector, "pi")
    command = HarnessCommand(session.session_id, "send_turn", {"text": "hello"})
    with pytest.raises(NativeAdapterError) as missing:
        connector.send(session, command)
    assert missing.value.details["not_sent"] is True

    connector._session_id = session.session_id
    connector._awaiting_settle_generation = 1
    with pytest.raises(NativeAdapterError) as unsettled:
        connector._guard_not_awaiting_settle("send_turn")
    assert unsettled.value.code == ErrorCode.CONFLICT
    assert unsettled.value.details["not_sent"] is True


def test_claude_stream_refuses_unstarted_and_full_queue_before_write():
    connector = ClaudeCodeStreamConnector()
    session = _session(connector, "claude_code")
    command = HarnessCommand(session.session_id, "send_turn", {"content": "hello"})
    with pytest.raises(NativeAdapterError) as unstarted:
        connector.send(session, command)
    assert unstarted.value.details["not_sent"] is True

    connector._pending_turns.extend([False] * 32)
    with pytest.raises(NativeAdapterError) as full:
        connector._check_turn_capacity()
    assert full.value.code == ErrorCode.CONFLICT
    assert full.value.details["not_sent"] is True


