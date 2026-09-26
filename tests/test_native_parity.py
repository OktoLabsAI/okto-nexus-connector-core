"""Selected legacy assertions from Nexus source SHA 7ed52c2, adapted to neutral events."""

import io

import pytest

from nexus_connector_core import RuntimeEvent
from nexus_connector_core.native.event_buffers import NativeEventQueue
from nexus_connector_core.native.framing import (
    MAX_FRAME_BYTES, ByteFrameLimitExceeded, FrameLimitExceeded,
    IncompleteByteFrame, byte_protocol_lines, protocol_lines,
)


def test_retained_terminal_drains_before_explicit_overflow():
    # tests/test_runtime_event_buffers.py:103-115 in the Nexus baseline.
    queue = NativeEventQueue(max_events=2)
    event = RuntimeEvent("srv", "exe", "fixture", "epoch", 1,
                         "turn_state", "turn/completed", {"text": "final"})
    assert queue.put(event)
    assert queue.put(event)
    assert not queue.put(event)
    assert queue.get(timeout=0) is event
    assert queue.get(timeout=0) is event
    with pytest.raises(RuntimeError, match="overflow"):
        queue.get(timeout=0)


def test_native_lf_framing_keeps_unicode_separators_inside_record():
    line = '{"text":"a\u2028b\u2029c"}\r\n'
    assert list(protocol_lines(io.StringIO(line))) == [line]


def test_native_framing_rejects_oversized_record():
    with pytest.raises(FrameLimitExceeded):
        list(protocol_lines(io.StringIO("x" * 262145)))


def test_native_byte_framing_preserves_utf8_and_unicode_separators():
    first = '{"text":"á\u2028b\u2029c"}'.encode("utf-8")
    assert list(byte_protocol_lines(io.BytesIO(first + b"\r\n{}\n"))) == [first, b"{}"]


def test_native_byte_framing_rejects_missing_lf_and_oversize():
    with pytest.raises(IncompleteByteFrame):
        list(byte_protocol_lines(io.BytesIO(b'{}')))
    with pytest.raises(ByteFrameLimitExceeded):
        list(byte_protocol_lines(io.BytesIO(b"x" * (MAX_FRAME_BYTES + 2))))
