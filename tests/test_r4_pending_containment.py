"""A retained renewal CAS cannot stall authorized containment of its session."""

import asyncio

import pytest

from nexus_connector_core import (
    ControlOperation, CoreError, OperationKey, ShutdownPolicy, TurnOperation,
    r4_close_operation, r4_native_decision_operation,
)
from test_runtime import FakeClock, FakeNative, make_runtime, _emit_durable_native_request
from test_r4_runtime_leases import attempt, grant, operation, open_session
from test_r4_decision_bridge import decision_frame


@pytest.mark.parametrize('action', ['turn.interrupt', 'runtime.close', 'approval.decide', 'input.provide'])
@pytest.mark.parametrize('expired', [False, True])
def test_containment_completes_while_renewal_cas_is_retained(tmp_path, action, expired):
    class Native(FakeNative):
        def __init__(self):
            super().__init__()
            self.replies = []

        async def reply_native_approval(self, request, decision, response):
            self.replies.append((decision, response))

    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        factory.native = Native()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        original = journal.cas_session_lease

        async def held(*args, **kwargs):
            calls.append(kwargs)
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        renewal = None
        try:
            req = await attempt(runtime, clock)
            actions = ['runtime.open', 'runtime.close', 'turn.submit', action]
            actions = list(dict.fromkeys(actions))
            installed = await runtime.install_r4_lease(req, grant(req, actions))
            await open_session(runtime, installed.context)
            if action in {'approval.decide', 'input.provide'}:
                payload = decision_frame(action)['payload']
                payload.update(decision='decline', response_digest=None)
                payload.pop('response', None)
                await _emit_durable_native_request(runtime, factory.native, payload['request'])
            elif action == 'runtime.close':
                payload = {'reason': 'Stop', 'drain_seconds': .1, 'interrupt_seconds': .1}
            else:
                payload = {'reason': 'Stop'}
            journal.cas_session_lease = held
            clock.advance(1)
            request = await attempt(runtime, clock, purpose='renew')
            renewal = asyncio.create_task(runtime.install_r4_lease(request, grant(request, actions)))
            await asyncio.wait_for(entered.wait(), 2)
            if expired:
                clock.advance(60)
            with pytest.raises(CoreError, match='LEASE_UPDATE_PENDING'):
                await runtime.submit(TurnOperation('productive', 'session', 'Hello'), installed.context)
            frame = operation(req, 'contain', action=action, payload=payload)
            context = runtime.r4_operation_context(frame, connection_id='connection', connection_generation=1)
            if action == 'turn.interrupt':
                result = await asyncio.wait_for(runtime.control(
                    ControlOperation('contain', 'session', 'interrupt', reason='Stop'), context), .5)
            elif action == 'runtime.close':
                result = await asyncio.wait_for(runtime.close(r4_close_operation(frame), context), .5)
                assert factory.native.stopped
            else:
                result = await asyncio.wait_for(runtime.decide_native_approval(
                    r4_native_decision_operation(frame), context), .5)
                assert factory.native.replies == [('decline', None)]
            assert result.stage == ('SUCCEEDED' if action == 'runtime.close' else 'SUBMITTED')
            assert not release.is_set() and not renewal.done() and len(calls) == 1
            assert await journal.get_receipt(OperationKey('srv', 'exe', 'productive')) is None
            release.set()
            if action == 'runtime.close' or expired:
                with pytest.raises(CoreError):
                    await renewal  # Late CAS cannot revive a closed or expired session.
            else:
                renewed = await renewal
                assert renewed.context.r4_authority.lease_serial == 2
                with pytest.raises(CoreError):
                    await runtime.submit(TurnOperation('stale', 'session', 'Hello'), installed.context)
                assert (await runtime.submit(TurnOperation('fresh', 'session', 'Hello'), renewed.context)).stage == 'SUBMITTED'
        finally:
            release.set()
            if renewal is not None:
                await asyncio.gather(renewal, return_exceptions=True)
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()

    asyncio.run(run())


@pytest.mark.parametrize('change', ['connection', 'scope', 'actions', 'revoked'])
def test_pending_renewal_never_lends_old_containment_to_new_authority(tmp_path, change):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        original = journal.cas_session_lease

        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        tasks = []
        try:
            req = await attempt(runtime, clock)
            installed = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, installed.context)
            clock.advance(1)
            fields = {'purpose': 'renew'}
            if change == 'connection':
                fields.update(purpose='reconnect', connection_id='new', connection_generation=2)
            if change == 'scope':
                fields['scope'] = {**req.scope, 'authorization_revision': 2}
            request = await attempt(runtime, clock, **fields)
            actions = ['runtime.open', 'turn.submit', 'runtime.close'] if change == 'actions' else None
            journal.cas_session_lease = held
            renewing = asyncio.create_task(runtime.install_r4_lease(request, grant(request, actions)))
            tasks.append(renewing)
            await asyncio.wait_for(entered.wait(), 2)
            if change == 'revoked':
                tasks.append(asyncio.create_task(runtime.revoke_r4_lease(installed.context, authorization_revision=2)))
                await asyncio.sleep(0)
            with pytest.raises(CoreError, match='AGENT_REVOKED' if change == 'revoked' else 'LEASE_UPDATE_PENDING'):
                await asyncio.wait_for(runtime.control(ControlOperation(
                    'forbidden', 'session', 'interrupt', reason='Stop'), installed.context), .5)
            assert not release.is_set() and not factory.native.sent
            assert await journal.get_receipt(OperationKey('srv', 'exe', 'forbidden')) is None
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()

    asyncio.run(run())


def test_renewal_during_containment_admission_returns_safe_retry(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        try:
            request = await attempt(runtime, clock)
            installed = await runtime.install_r4_lease(request, grant(request))
            await open_session(runtime, installed.context)
            clock.advance(1)
            renewal = await attempt(runtime, clock, purpose='renew')
            original = journal.get_receipt
            renewed = None

            async def race(key):
                nonlocal renewed
                result = await original(key)
                if key.operation_id == 'contain' and renewed is None:
                    renewed = await runtime.install_r4_lease(renewal, grant(renewal))
                return result

            journal.get_receipt = race
            operation = ControlOperation('contain', 'session', 'interrupt', reason='Stop')
            with pytest.raises(CoreError, match='STALE_GENERATION') as failure:
                await runtime.control(operation, installed.context)
            assert failure.value.retry_safe and not failure.value.possible_effect
            assert not factory.native.sent
            assert await original(OperationKey('srv', 'exe', 'contain')) is None
            result = await runtime.control(operation, renewed.context)
            assert result.stage == 'SUBMITTED'
            assert len(factory.native.sent) == 1
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()

    asyncio.run(run())
