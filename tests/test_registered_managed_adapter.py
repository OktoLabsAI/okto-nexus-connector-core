"""Trusted additional connectors traverse the production Core factory."""
import asyncio
import queue
import subprocess
import sys
from pathlib import Path

import pytest

from nexus_connector_core import ControlTargeting, build_executor_inventory_snapshot, verify_executor_inventory_snapshot
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate, LaunchIntent, OpenOperation, ShutdownPolicy, TurnOperation
from nexus_connector_core.native import registry
from nexus_connector_core.native.adapter_types import HarnessCapabilities, HarnessSession, DispatchGuards
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.runtime import LocalRuntimeCore
from test_native_runtime_bridge import context

ADAPTER = 'fixture.processless.v1'


class ProcesslessConnector:
    instances = []
    protocol = {'managed_contract': 1, 'transport_binding_contract': 1}

    def __init__(self, *, command, cwd, env):
        self.closed = False
        self.sent = []
        self.contexts = []
        self.queue = queue.Queue()
        self._dispatch_guards = DispatchGuards()
        self.instances.append(self)

    def start(self, *, owning_agent_id):
        self._launch_guard('fixture_start')
        self.session = HarnessSession('native-processless', ADAPTER, owning_agent_id,
            'RUNNING', HarnessCapabilities(True, None, False, False, True), '2026-10-08T00:00:00Z')
        return self.session

    def verify_protocol(self):
        return dict(self.protocol)

    def send(self, session, command):
        self._dispatch_guards.check()
        self.sent.append(command)
        if command.verb == 'end':
            self.close()

    def events(self):
        while (item := self.queue.get()) is not None:
            yield item

    def observe_context(self, session, envelope):
        self._dispatch_guards.check()
        self.contexts.append(envelope)

    def close(self):
        self.closed = True
        self.queue.put(None)
        return 'graceful'

    force_stop = close

    def observe_lifecycle(self, session):
        return {'stop_observed': self.closed}


@pytest.mark.parametrize('observed', [1, 2, True])
def test_registered_processless_factory_checks_its_own_contract(tmp_path, monkeypatch, observed):
    monkeypatch.setitem(registry._SPECS, ADAPTER, registry.AdapterSpec(
        ADAPTER, ADAPTER, __name__, 'ProcesslessConnector', 'managed', None,
        frozenset({sys.platform}),
        (ControlTargeting('turn.steer', False, 'forbidden', False),
         ControlTargeting('turn.interrupt', False, 'forbidden', False)),
        managed_contract=1, transport_binding_contract=1))
    monkeypatch.setattr(ProcesslessConnector, 'instances', [])
    monkeypatch.setattr(ProcesslessConnector, 'protocol',
        {'managed_contract': observed, 'transport_binding_contract': 1})
    real_popen = subprocess.Popen
    def no_process(*args, **kwargs):
        # Both inventory and opening inspect the macOS containment domain.
        # Permit only that exact read-only host query, never an adapter launch.
        if sys.platform == 'darwin' and args and args[0] == ['/bin/launchctl', 'managername']:
            return real_popen(*args, **kwargs)
        raise AssertionError('The processless connector must not execute the selected anchor')
    monkeypatch.setattr(subprocess, 'Popen', no_process)

    async def run():
        candidate = InstallationCandidate(ADAPTER, sys.executable, fingerprint(Path(sys.executable)),
            'explicit', 'selected')
        snapshot = build_executor_inventory_snapshot((candidate,), server_id='srv', executor_id='exe',
            producer_instance_id='fixture', publication_sequence=1)
        verify_executor_inventory_snapshot(snapshot)
        async def environment(prepared):
            return {}
        factory = CopiedAdapterFactory(environment)
        journal = SQLiteJournal(tmp_path / 'registered.db')
        runtime = LocalRuntimeCore(journal, factory, candidates={ADAPTER: candidate},
            workspace_roots={'ws': str(tmp_path)})
        try:
            prepared = await runtime.prepare(LaunchIntent('agent', 'ws', ADAPTER), context())
            opening = OpenOperation('open-registered', 'session', 'epoch', prepared)
            if type(observed) is int and observed == 1:
                receipt = await runtime.open(opening, context())
                assert receipt.stage == 'SUBMITTED', receipt
                receipt = await runtime.submit(TurnOperation('turn-registered', 'session', 'hello'), context())
                assert receipt.stage == 'SUBMITTED'
                commands = ProcesslessConnector.instances[0].sent
                assert len(commands) == 1
                assert commands[0].payload == {'text': 'hello'}
                assert commands[0].operation_id == 'turn-registered'
            else:
                receipt = await runtime.open(opening, context())
                assert receipt.stage == 'FAILED', receipt
                assert ProcesslessConnector.instances[0].closed
                assert not ProcesslessConnector.instances[0].sent
        finally:
            await runtime.shutdown(ShutdownPolicy(1, 1))
            factory.close()
            journal.close()
    asyncio.run(run())


@pytest.mark.parametrize('contract', [None, True, 1])
def test_context_storage_requires_observed_contract_scope_and_final_host_guard(tmp_path, monkeypatch, contract):
    from nexus_connector_core.models import SessionKey, EffectNotSent
    monkeypatch.setitem(registry._SPECS, ADAPTER, registry.AdapterSpec(
        ADAPTER, ADAPTER, __name__, 'ProcesslessConnector', 'managed', None,
        frozenset({sys.platform}), (), managed_contract=1, transport_binding_contract=1,
        context_observation_contract=1))
    monkeypatch.setattr(ProcesslessConnector, 'instances', [])
    monkeypatch.setattr(ProcesslessConnector, 'protocol', dict(managed_contract=1,
        transport_binding_contract=1, context_observation_contract=contract))
    async def run():
        candidate = InstallationCandidate(ADAPTER, sys.executable, fingerprint(Path(sys.executable)), 'explicit', 'selected')
        async def environment(prepared):
            return {}
        factory = CopiedAdapterFactory(environment)
        journal = SQLiteJournal(tmp_path / 'context.db')
        runtime = LocalRuntimeCore(journal, factory, candidates={ADAPTER: candidate}, workspace_roots={'ws': str(tmp_path)})
        ctx = context()
        key = SessionKey(ctx.server_id, ctx.executor_id, 'session')
        envelope = dict(intent='information', response_requested=False,
                        recipient_agent_id=ctx.agent_id, workspace_id=ctx.workspace_id, content=['context'])
        try:
            prepared = await runtime.prepare(LaunchIntent('agent', 'ws', ADAPTER), ctx)
            await runtime.open(OpenOperation('context-open', 'session', 'epoch', prepared), ctx)
            peer = ProcesslessConnector.instances[0]
            qualified = type(contract) is int and contract == 1
            assert runtime.context_observation_supported(key) is qualified
            if not qualified:
                with pytest.raises(EffectNotSent):
                    await runtime.observe_context(key, envelope, guard=lambda: None)
            else:
                def revoked():
                    raise EffectNotSent('Host authority revoked')
                with pytest.raises(EffectNotSent):
                    await runtime.observe_context(key, envelope, guard=revoked)
                with pytest.raises(EffectNotSent):
                    await runtime.observe_context(key, dict(envelope, workspace_id='another'), guard=lambda: None)
                assert peer.contexts == []
                await runtime.observe_context(key, envelope, guard=lambda: None)
                assert peer.contexts == [envelope] and peer.contexts[0] is not envelope
            assert peer.sent == []
        finally:
            await runtime.shutdown(ShutdownPolicy(1, 1))
            factory.close()
            journal.close()
    asyncio.run(run())
