"""Claude's final assistant message replaces its streamed deltas."""
from dataclasses import replace
from queue import Queue
from types import SimpleNamespace

import pytest

from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.event_ingest import translate_native_event
from nexus_connector_core.native.redaction import NativeSecretRedactor


@pytest.mark.parametrize('prefix', [None, 'draft that must be replaced'])
@pytest.mark.parametrize('final_text', ['final response', '', 'safe secret-token'])
def test_result_text_is_a_redacted_snapshot_before_the_terminal(prefix, final_text):
    import asyncio
    from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession

    async def run():
        connector = ClaudeCodeStreamConnector(binary='unused')
        connector._session = SimpleNamespace(session_id='native')
        observed = Queue()
        connector._subscribers.append(observed)
        connector.events = lambda: iter(list(observed.queue))
        bridge = CopiedAdapterSession(connector, connector._session,
            session_id='session', stream_epoch='epoch',
            context=SimpleNamespace(server_id='server', executor_id='executor'),
            redactor=NativeSecretRedactor(['secret-token']))
        try:
            for number in range(2):
                observed.queue.clear()
                bridge._active_operation_id = f'op-{number}'
                if prefix is not None:
                    connector._handle_stream_event({'event': {'type': 'content_block_delta',
                        'delta': {'type': 'text_delta', 'text': prefix}}})
                connector._handle_result({'type': 'result', 'subtype': 'success', 'result': final_text})
                events = [event async for event in bridge.events()]
                output = ''
                for event in events:
                    assert event.operation_id == f'op-{number}'
                    assert 'secret-token' not in str(event.payload)
                    if event.category == 'text_snapshot':
                        output = ''
                    output += event.payload.get('output_text') or ''
                assert events[-1].category == 'turn_state'
                assert events[-1].payload['delivery_phase'] == 'terminal'
                assert any(event.category == 'text_snapshot' for event in events)
                assert output == final_text.replace('secret-token', '[REDACTED]')
        finally:
            bridge._control_executor.shutdown()
            bridge._force_executor.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('final_text', ['NEXUS_CLAUDE_UI_OK', '', 'safe secret-token'])
def test_stream_snapshot_and_terminal_tail_publish_once(final_text):
    connector = ClaudeCodeStreamConnector(binary='unused')
    connector._session = SimpleNamespace(session_id='session')
    observed = Queue()
    connector._subscribers.append(observed)
    connector._handle_stream_event({'event': {'type': 'content_block_delta',
        'delta': {'type': 'text_delta', 'text': 'draft that must be replaced'}}})
    connector._handle_assistant({'message': {'content': [{'type': 'text', 'text': final_text}]}})
    delta, snapshot = observed.get_nowait(), observed.get_nowait()
    assert snapshot.output_snapshot and not delta.output_snapshot
    terminal = replace(snapshot, kind='turn_completed', native_event='result:success',
                       payload={}, output_snapshot=False, delivery_phase='terminal')
    redactor = NativeSecretRedactor(['secret-token'])
    text = ''
    for native in (delta, snapshot, terminal):
        event = translate_native_event(redactor.scrub(native), server_id='server',
            executor_id='executor', session_id='session', stream_epoch='epoch')
        if event.category == 'text_snapshot':
            text = ''
        text += event.payload.get('output_text') or ''
        assert 'secret-token' not in str(event.payload)
    assert text == final_text.replace('secret-token', '[REDACTED]')


def test_runtime_bridge_preserves_long_response_prefix_and_next_turn():
    import asyncio
    from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession

    async def run():
        connector = ClaudeCodeStreamConnector(binary='unused')
        connector._session = SimpleNamespace(session_id='native')
        observed = Queue()
        connector._subscribers.append(observed)
        connector.events = lambda: iter(list(observed.queue))
        bridge = CopiedAdapterSession(connector, connector._session,
            session_id='session', stream_epoch='epoch',
            context=SimpleNamespace(server_id='server', executor_id='executor'))
        try:
            for number in range(2):
                observed.queue.clear()
                text = f'INICIO {number}: ' + ('Resposta completa com acentuação. ' * 20) + ' FIM'
                bridge._active_operation_id = f'op-{number}'
                for offset in range(0, len(text), 17):
                    connector._handle_stream_event({'event': {'type': 'content_block_delta',
                        'delta': {'type': 'text_delta', 'text': text[offset:offset+17]}}})
                connector._handle_assistant({'message': {'content': [{'type': 'text', 'text': text}]}})
                connector._handle_result({'type': 'result', 'subtype': 'success'})
                output = ''
                async for event in bridge.events():
                    assert event.operation_id == f'op-{number}'
                    if event.category == 'text_snapshot':
                        output = ''
                    output += event.payload.get('output_text') or ''
                assert output == text
        finally:
            bridge._control_executor.shutdown()
            bridge._force_executor.shutdown()
    asyncio.run(run())
