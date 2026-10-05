"""Pi text belongs to its active operation; thinking is never reply text."""
import asyncio
from queue import Queue
from types import SimpleNamespace

from nexus_connector_core.native.adapters.pi import PiRpcConnector
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession


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
