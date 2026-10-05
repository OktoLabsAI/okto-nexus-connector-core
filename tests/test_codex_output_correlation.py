import asyncio
from types import SimpleNamespace
import pytest

from nexus_connector_core.models import CoreError
from nexus_connector_core.native.adapter_types import HarnessEvent
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession


@pytest.mark.parametrize('delta_turn', ['turn', 'stale', None])
def test_codex_text_preserves_prefix_and_rejects_other_turn(delta_turn):
    async def run():
        text = 'CODEX_RUNTIME_OK — the entire reply must survive redaction holdback.'
        events = [HarnessEvent('native', 'codex', 'turn_started', 'turn/started', '', {},
                              turn_id='turn', delivery_phase='started')]
        events += [HarnessEvent('native', 'codex', 'output_delta', 'item/agentMessage/delta', '',
                               {'delta': text[i:i+3]}, turn_id=delta_turn)
                   for i in range(0, len(text), 3)]
        events.append(HarnessEvent('native', 'codex', 'turn_completed', 'turn/completed', '', {},
                                  turn_id='turn', delivery_phase='terminal', delivery_outcome='success'))
        connector = SimpleNamespace(events=lambda: iter(events))
        bridge = CopiedAdapterSession(connector, SimpleNamespace(session_id='native'),
            session_id='session', stream_epoch='epoch',
            context=SimpleNamespace(server_id='server', executor_id='executor'))
        bridge._active_operation_id = 'op'
        async def collect():
            output = ''
            async for event in bridge.events():
                chunk = event.payload.get('output_text')
                if chunk is not None:
                    assert event.operation_id == 'op'
                    output += chunk
            return output
        try:
            if delta_turn == 'turn':
                assert await collect() == text
            else:
                with pytest.raises(CoreError, match='EVENT_OPERATION_MISMATCH'):
                    await collect()
        finally:
            bridge._control_executor.shutdown()
            bridge._force_executor.shutdown()
    asyncio.run(run())
