"""Claude's final assistant message replaces its streamed deltas."""
from dataclasses import replace
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.claude_chat_facts import CLAUDE_STREAM_CHAT_EVENT
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


def test_stream_chat_snapshot_preserves_explicit_child_scope_and_verified_turn():
    import asyncio
    from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession

    async def run():
        session = str(uuid4())
        child = "toolu_owned_child"
        connector = ClaudeCodeStreamConnector(binary="unused")
        connector._session = SimpleNamespace(session_id="native")
        queue = Queue()
        connector._subscribers.append(queue)
        connector.events = lambda: iter(list(queue.queue))
        bridge = CopiedAdapterSession(connector, connector._session, session_id="session", stream_epoch="epoch",
            context=SimpleNamespace(server_id="server", executor_id="executor"),
            redactor=NativeSecretRedactor(["secret-token"]))
        bridge._active_operation_id = "exact-turn"
        connector._append_pending_turn("exact-turn")
        connector._handle_system({"subtype": "init", "session_id": session})

        def assistant(parts, parent=None, **override):
            frame = {"session_id": session, "uuid": str(uuid4()), "parent_tool_use_id": parent,
                     "message": {"id": "msg_shared_by_blocks", "role": "assistant", "content": parts}} | override
            connector._handle_assistant(frame)
            return frame["uuid"]

        try:
            assistant([{"type": "thinking", "thinking": "private reasoning"},
                       {"type": "tool_use", "id": child, "name": "Agent", "input": {}}])
            rejected = [{"type": "text", "text": "must not project"}]
            assistant(rejected, "toolu_unknown")
            assistant(rejected, child, session_id=str(uuid4()))
            assistant(rejected, child, uuid="no-native-id")
            child_id = assistant([{"type": "text", "text": "same secret-token"}], child)
            root_id = assistant([{"type": "text", "text": "same secret-token"}])
            connector._handle_result({"subtype": "success", "session_id": session, "result": "Terminal result"})
            assistant(rejected, child)
            facts = [event async for event in bridge.events() if event.native_type == CLAUDE_STREAM_CHAT_EVENT]
            assert len(facts) == 2
            for event, entry, parent in zip(facts, [child_id, root_id], [child, None], strict=True):
                assert event.operation_id == "exact-turn"
                assert event.payload == {"revision": 1, "native_session_id": session, "entry_id": entry,
                    "parent_tool_use_id": parent, "role": "assistant", "text": "same [REDACTED]"}
        finally:
            bridge._control_executor.shutdown()
            bridge._force_executor.shutdown()
    asyncio.run(run())
