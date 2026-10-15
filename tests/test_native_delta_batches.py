"""Real adapter subscriptions survive a token burst while the reader is paused."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from nexus_connector_core.native.adapter_types import HarnessEvent
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector
from nexus_connector_core.native.delta_batches import coalesce_claude_delta, coalesce_codex_delta
from nexus_connector_core.native.event_buffers import NativeEventQueue, NativeEventOverflow


@pytest.mark.parametrize('adapter', ['claude', 'codex'])
def test_actual_subscription_preserves_burst_final_and_next_turn(adapter):
    if adapter == 'claude':
        connector = ClaudeCodeStreamConnector(binary='unused')
        connector._session = SimpleNamespace(session_id='native')
        def emit(kind, payload):
            if kind == 'delta':
                connector._handle_stream_event({'event': {'type': 'content_block_delta',
                    'index': 0, 'delta': {'type': 'text_delta', 'text': payload}}})
            elif kind == 'end':
                connector._handle_result({'type': 'result', 'subtype': 'success', 'result': payload})
            else:
                connector._emit('turn_started', 'system:init', {})
        stream = connector.events()
        delta_name, text_key, end_name = 'stream_event:content_block_delta', 'text', 'result:success'
    else:
        connector = CodexAppServerConnector(command=('unused',))
        def emit(kind, payload):
            method, params = {'delta': ('item/agentMessage/delta', {'delta': payload, 'itemId': 'item'}),
                'end': ('turn/completed', {'turn': {'id': 'turn', 'status': 'completed'}}),
                'start': ('turn/started', {'turn': {'id': 'turn'}})}[kind]
            connector._push_event('native', method, params, thread_id='thread', turn_id='turn')
        stream = connector.events(session_id='native')
        delta_name, text_key, end_name = 'item/agentMessage/delta', 'delta', 'turn/completed'
    try:
        emit('start', '')
        next(stream)  # Register the actual adapter subscriber.
        for turn in range(2):
            chunks = [f'{turn}:{i}: ação 🟢\n' for i in range(1800)]
            for chunk in chunks:
                emit('delta', chunk)
            emit('end', ''.join(chunks))
            items = []
            while True:
                event = next(stream)
                items.append(event)
                if event.native_event == end_name:
                    break
            assert ''.join(e.payload[text_key] for e in items if e.native_event == delta_name) == ''.join(chunks)
            assert len(items) < 20
            assert not connector._subscribers[0]._overflow
            # The old non-coalescing queue fails with this same token burst.
            old = NativeEventQueue()
            sample = next(e for e in items if e.native_event == delta_name)
            for chunk in chunks:
                old.put(replace(sample, payload={text_key: chunk}))
            for _ in range(old.qsize()):
                old.get(timeout=0)
            with pytest.raises(NativeEventOverflow):
                old.get(timeout=0)
            emit('start', '')
            assert next(stream).kind == 'turn_started'
    finally:
        stream.close()


def event(adapter='claude', **kw):
    base = HarnessEvent('native', 'claude_code' if adapter == 'claude' else 'codex',
        'output_delta', 'stream_event:content_block_delta' if adapter == 'claude' else 'item/agentMessage/delta',
        'now', {'text': 'a', 'index': 0} if adapter == 'claude' else {'delta': 'a', 'itemId': 'a'})
    return replace(base, **kw)


@pytest.mark.parametrize('adapter,merge', [('claude', coalesce_claude_delta), ('codex', coalesce_codex_delta)])
@pytest.mark.parametrize('change', [
    {'session_id': 'other'}, {'operation_id': 'other'}, {'turn_id': 'other'},
    {'thread_id': 'other'}, {'attempt_id': 'other'}, {'owner_epoch': 2},
    {'native_event': 'boundary'}, {'output_snapshot': True}, {'kind': 'turn_completed'},
    {'native_approval': {'request_id': 'approval'}}, {'sequence': 2},
])
def test_never_crosses_identity_or_control_boundaries(adapter, merge, change):
    first = event(adapter)
    assert merge(first, replace(first, **change)) is None


@pytest.mark.parametrize('adapter,merge,key', [('claude', coalesce_claude_delta, 'text'), ('codex', coalesce_codex_delta, 'delta')])
def test_batches_bounded_utf8_and_preserves_original_events(adapter, merge, key):
    first = event(adapter)
    q = NativeEventQueue(coalesce=merge)
    originals = []
    for _ in range(1000):
        native = replace(first, payload=dict(first.payload, **{key: '🟢' * 20}))
        originals.append(native)
        assert q.put(native)
    items = [q.get(timeout=0) for _ in range(q.qsize())]
    assert len(items) > 1
    assert all(len(json.dumps(e.payload, ensure_ascii=False).encode()) <= 24 * 1024 for e in items)
    assert ''.join(e.payload[key] for e in items) == '🟢' * 20000
    assert all(e.payload[key] == '🟢' * 20 for e in originals)
    assert q._bytes == 0
    changed = dict(first.payload, **({'index': 1} if adapter == 'claude' else {'itemId': 'other'}))
    assert merge(first, replace(first, payload=changed)) is None


@pytest.mark.parametrize('kind,key', [('thinking_delta','thinking'), ('input_json_delta','partial_json'), ('signature_delta','signature')])
def test_claude_non_text_fragments_preserve_kind_and_block(kind, key):
    a = event(kind='tool_activity', payload={'event': {'type': 'content_block_delta',
        'index': 1, 'delta': {'type': kind, key: 'a'}}})
    b = replace(a, payload={'event': {'type': 'content_block_delta',
        'index': 1, 'delta': {'type': kind, key: 'b'}}})
    merged = coalesce_claude_delta(a, b)
    assert merged.kind == 'tool_activity'
    assert merged.payload['event']['delta'] == {'type': kind, key: 'ab'}
    assert coalesce_claude_delta(a, replace(b, payload={'event': dict(b.payload['event'], index=2)})) is None


def test_unbatchable_overload_is_still_explicit():
    q = NativeEventQueue(max_events=2, coalesce=coalesce_claude_delta)
    boundary = event(kind='tool_activity', native_event='control_request:can_use_tool')
    assert q.put(boundary) and q.put(boundary)
    assert not q.put(boundary)
    assert q.get(timeout=0) == boundary and q.get(timeout=0) == boundary
    with pytest.raises(NativeEventOverflow):
        q.get(timeout=0)
