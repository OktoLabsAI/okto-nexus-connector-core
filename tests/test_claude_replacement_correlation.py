"""Claude replacement steering retains distinct original/replacement results."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

from nexus_connector_core.native.adapter_types import RuntimeCommandNotSent
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession


def test_replacement_result_keeps_its_operation_after_interrupted_original(tmp_path):
    async def run():
        script = Path(__file__).parent / 'fixtures/claude_stream_peer.py'
        connector = ClaudeCodeStreamConnector(binary=sys.executable,
            argv=['-u', '-c', script.read_text(encoding='utf-8')], cwd=str(tmp_path),
            env={'FAKE_CC_SCENARIO': 'slow_start'})
        native = await asyncio.to_thread(connector.start, owning_agent_id='subject')
        bridge = CopiedAdapterSession(connector, native, session_id='session', stream_epoch='epoch',
            context=SimpleNamespace(server_id='server', executor_id='executor'))
        started = asyncio.Event()
        observed = []
        async def collect():
            async for event in bridge.events():
                observed.append(event)
                if event.native_type == 'stream_event:content_block_start':
                    started.set()
                if sum(e.payload.get('delivery_phase') == 'terminal' for e in observed) == 2:
                    return
        consumer = asyncio.create_task(collect())
        try:
            await bridge.send('send_turn', {'text': 'first'}, 'original')
            try:
                await bridge.send('steer', {'text': 'too early'}, 'refused')
            except RuntimeCommandNotSent:
                pass
            else:
                raise AssertionError('Requesting-phase steer must remain a no-write refusal')
            assert list(bridge._replacement_operations) == []
            await asyncio.wait_for(started.wait(), 10)
            await bridge.send('steer', {'text': 'replacement'}, 'replacement')
            await asyncio.wait_for(consumer, 15)
            terminals = [e for e in observed if e.payload.get('delivery_phase') == 'terminal']
            assert [e.operation_id for e in terminals] == ['original', 'replacement']
            assert [e.payload['delivery_outcome'] for e in terminals] == ['interrupted', 'success']
            text = {}
            for event in observed:
                if event.category == 'text_snapshot':
                    text[event.operation_id] = ''
                text[event.operation_id] = text.get(event.operation_id, '') + (event.payload.get('output_text') or '')
            assert 'echo:replacement' in text['replacement']
            assert 'replacement' not in text['original']
            assert 'refused' not in text
            assert not bridge.active_turn() and not bridge._replacement_operations
        finally:
            await bridge.close()
            await asyncio.gather(consumer, return_exceptions=True)
    asyncio.run(run())
