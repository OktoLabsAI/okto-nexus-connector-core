import asyncio
from dataclasses import replace
import json
import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.native_action_bridge import (
    AgentList, AgentGet, CapabilityList, CoordinationHealth, ScopedNativeActionBridge,
)
from nexus_connector_core.native_action_socket import _decode_request
from test_native_action_bridge import Clock, context, grant


@pytest.mark.parametrize('query,action', [
    (AgentList('read', 'session', 'native-cap:session'), 'agent.list'),
    (AgentGet('read', 'session', 'native-cap:session', 'other'), 'agent.get'),
    (CapabilityList('read', 'session', 'native-cap:session'), 'capability.list'),
    (CoordinationHealth('read', 'session', 'native-cap:session'), 'coordination.health'),
])
def test_native_discovery_requires_scoped_authority_and_reads_have_no_possible_effect(query, action):
    class Backend:
        calls = 0
        async def read_discovery(self, request, context):
            self.calls += 1
            raise OSError('read interrupted')
    async def run():
        backend = Backend()
        allowed = frozenset({action})
        ctx = replace(context(), allowed_actions=allowed)
        active = replace(grant(), allowed_actions=allowed)
        for authority, execution in [(grant(), ctx), (active, replace(ctx, agent_id='other')),
                                      (replace(active, expires_monotonic=99), ctx)]:
            with pytest.raises(CoreError):
                await ScopedNativeActionBridge(backend, authority, clock=Clock()).invoke(query, execution)
        assert backend.calls == 0
        with pytest.raises(CoreError) as error:
            await ScopedNativeActionBridge(backend, active, clock=Clock()).invoke(query, ctx)
        assert error.value.code == 'EXECUTOR_OFFLINE' and not error.value.possible_effect and error.value.retry_safe
        assert backend.calls == 1
    asyncio.run(run())


@pytest.mark.parametrize('action', ['agent.list', 'agent.get', 'capability.list', 'coordination.health'])
def test_native_discovery_socket_cannot_override_workspace_or_sender(action):
    body = dict(action=action, operation_id='op', session_id='session', capability_ref='native-cap:session')
    if action == 'agent.get':
        body['agent_id'] = 'other'
    for extra in ({'workspace_id': 'foreign'}, {'from_agent_id': 'operator'}, {'method': 'tools/call'}):
        with pytest.raises(CoreError):
            _decode_request(json.dumps(body | extra).encode() + b'\n')
