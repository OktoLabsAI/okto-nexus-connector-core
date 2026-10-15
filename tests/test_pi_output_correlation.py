"""Pi text belongs to its active operation; thinking is never reply text."""
import asyncio
from queue import Queue
from types import SimpleNamespace

from nexus_connector_core.native.adapters.pi import PiRpcConnector
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession


def test_pi_burst_batches_without_losing_text_or_terminal_boundaries():
    from nexus_connector_core.native.event_buffers import NativeEventHistory, subscribe
    from nexus_connector_core.native.adapters.pi import _coalesce_message_delta
    connector = PiRpcConnector(command=('unused',))
    connector._session_id = 'native'
    q, _ = subscribe(NativeEventHistory(), connector._subscribers, coalesce=_coalesce_message_delta)
    connector._on_push_event({'type': 'agent_start'})
    expected = ''.join(f'{i}: ação 🟢\n' for i in range(600))
    for offset in range(0, len(expected), 3):
        connector._on_push_event({'type':'message_update', 'assistantMessageEvent':
            {'type':'text_delta', 'contentIndex':0, 'delta':expected[offset:offset+3]}})
    connector._on_push_event({'type':'message_end','message':{'role':'assistant','stopReason':'stop'}})
    connector._on_push_event({'type':'agent_settled'})
    events = [q.get(timeout=0) for _ in range(q.qsize())]
    assert events[0].native_event == 'agent_start'
    assert [e.native_event for e in events[-2:]] == ['message_end','agent_settled']
    assert ''.join(e.payload['assistantMessageEvent']['delta'] for e in events if e.native_event == 'message_update') == expected
    assert len(events) < 20
    assert not q._overflow and q._bytes == 0


def test_pi_batching_preserves_thinking_text_and_tool_boundaries():
    from nexus_connector_core.native.event_buffers import NativeEventQueue
    from nexus_connector_core.native.adapters.pi import _coalesce_message_delta
    connector = PiRpcConnector(command=('unused',))
    connector._session_id = 'native'
    q = NativeEventQueue(coalesce=_coalesce_message_delta)
    connector._subscribers.append(q)
    for kind, index in [('thinking_delta',0),('text_delta',1),('toolcall_delta',2)]:
        for text in ['a','b']:
            connector._on_push_event({'type':'message_update','assistantMessageEvent':
                {'type':kind,'contentIndex':index,'delta':text}})
    assert q.qsize() == 3
    assert [(e.payload['assistantMessageEvent']['type'],e.payload['assistantMessageEvent']['delta'])
        for e in [q.get(timeout=0) for _ in range(3)]] == [
            ('thinking_delta','ab'),('text_delta','ab'),('toolcall_delta','ab')]


def test_pi_reply_prefix_and_next_turn_exclude_thinking():
    async def run():
        connector = PiRpcConnector(command=('unused',))
        connector._session_id = 'native'
        observed = Queue()
        connector._subscribers.append(observed)
        connector.events = lambda: iter(list(observed.queue))
        bridge = CopiedAdapterSession(connector, SimpleNamespace(session_id='native'),
            session_id='session', stream_epoch='epoch',
            context=SimpleNamespace(server_id='server', executor_id='executor'))
        try:
            for number in range(2):
                observed.queue.clear()
                bridge._active_operation_id = f'op-{number}'
                connector._on_push_event({'type': 'agent_start'})
                connector._on_push_event({'type': 'message_update',
                    'assistantMessageEvent': {'type': 'thinking_delta', 'delta': 'private thinking'}})
                text = f'PI_RUNTIME_OK {number} — mensagem recebida integralmente.'
                for offset in range(0, len(text), 3):
                    connector._on_push_event({'type': 'message_update',
                        'assistantMessageEvent': {'type': 'text_delta', 'delta': text[offset:offset+3]}})
                connector._on_push_event({'type': 'message_end',
                    'message': {'role': 'assistant', 'stopReason': 'stop'}})
                connector._on_push_event({'type': 'agent_settled'})
                output = ''
                async for event in bridge.events():
                    chunk = event.payload.get('output_text')
                    if chunk is not None:
                        assert event.operation_id == f'op-{number}'
                        output += chunk
                assert output == text
        finally:
            bridge._control_executor.shutdown()
            bridge._force_executor.shutdown()
    asyncio.run(run())
