from types import SimpleNamespace
import pytest

from nexus_connector_core import discover_harness_configuration
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [False, True])
async def test_configuration_observation_is_bounded_metadata_or_redacted_warning(failure):
    def observe():
        if failure:
            raise ConnectionError('secret-credential must not escape')
        return discover_harness_configuration('pi_rpc', native_models={
            'models':[{'id':'m','provider':'p'}]})
    connector = SimpleNamespace(configuration_observation=observe,
        _configuration_candidate_ref='installation', events=lambda:iter([]))
    bridge = CopiedAdapterSession(connector, SimpleNamespace(session_id='native'),
        session_id='session', stream_epoch='epoch',
        context=SimpleNamespace(server_id='server',executor_id='executor'))
    try:
        events = [e async for e in bridge.events()]
        assert len(events) == 1
        assert events[0].operation_id is None
        assert events[0].native_type == 'core/harness_configuration'
        if failure:
            assert events[0].category == 'system_warning'
            assert 'secret-credential' not in str(events)
        else:
            assert events[0].payload['harness_configuration']['candidate_ref'] == 'installation'
            assert events[0].payload['harness_configuration']['models'][0]['provider'] == 'p'
    finally:
        bridge._control_executor.shutdown()
        bridge._force_executor.shutdown()
