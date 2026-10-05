"""R4 grants are installed in the runtime before prepare or native effect."""

import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import (
    CloseOperation, ControlOperation, CoreError, LaunchIntent, NativeApprovalOperation,
    OpenOperation, OperationKey, R4LeaseAttempt,
    R4_PREVIEW_REVISION, SessionKey, ShutdownPolicy, TurnOperation,
    r4_submit_intent_hash, project_r4_turn_receipt,
    r4_native_decision_operation,
)
from test_runtime import FakeClock, make_runtime


async def attempt(runtime, clock, **changes):
    fields = dict(scope=dict(server_id='srv', executor_id='exe', binding_id='binding',
                             agent_id='agent', workspace_id='ws', workspace_binding_id='wxb',
                             session_id='session', session_owner_generation=1,
                             authorization_revision=1, configuration_revision=1,
                             binding_revision=1, credential_epoch=1),
                  grant_id='grant', connection_id='connection',
                  connection_generation=1, purpose='initial')
    fields.update(changes)
    return await runtime.begin_r4_lease_request(**fields)


def grant(request, actions=None, duration=60000):
    return dict(protocol_major=1, contract_revision=R4_PREVIEW_REVISION,
                type="lease.granted", request_id=request.request_id, lease_id="lease",
                lease_serial=request.expected_lease_serial + 1, grant_id=request.grant_id,
                scope=dict(request.scope), valid_for_ms=duration,
                allowed_actions=list(actions if actions is not None else
                                     ["runtime.open", "turn.submit", "turn.interrupt", "runtime.close"]))


def operation(request, operation_id="turn", **changes):
    frame = dict(protocol_major=1, contract_revision=R4_PREVIEW_REVISION,
                 type="operation.submit", **request.scope,
                 connection_id=request.connection_id,
                 connection_generation=request.connection_generation,
                 grant_id=request.grant_id, operation_id=operation_id,
                 action="turn.submit", payload={"text": "Hello", "delivery_id": "delivery"})
    frame.update(changes)
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    return frame


async def open_session(runtime, context):
    prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"), context)
    return await runtime.open(OpenOperation("open", "session", "epoch", prepared), context)


def test_initial_application_binds_full_scope_before_effect_and_preserves_replay(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        req = await attempt(runtime, clock)
        try:
            with pytest.raises(CoreError):
                runtime.r4_operation_context(operation(req), connection_id="connection", connection_generation=1)
            installed = await runtime.install_r4_lease(req, grant(req))
            context = installed.context
            assert context.r4_authority.workspace_binding_id == "wxb"
            assert context.r4_authority.lease_serial == 1
            assert installed.acknowledgement["application_stage"] == "INSTALLED"
            assert factory.open_count == 0
            assert await journal.get_receipt(OperationKey("srv", "exe", "open")) is None
            installed.acknowledgement["scope"]["agent_id"] = "tampered"
            clock.advance(2)
            replay = await runtime.install_r4_lease(req, grant(req))
            assert replay.context == context
            assert replay.acknowledgement["scope"]["agent_id"] == "agent"
            for changed in (
                replace(context, allowed_actions=context.allowed_actions | {"turn.steer"}),
                replace(context, lease_deadline_monotonic=context.lease_deadline_monotonic + 100),
                replace(context, r4_authority=replace(context.r4_authority, workspace_binding_id="other")),
            ):
                with pytest.raises(CoreError):
                    await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"), changed)
            await open_session(runtime, context)
            for field, value in (("workspace_binding_id", "other"), ("binding_revision", 2),
                                  ("credential_epoch", 2), ("session_owner_generation", 2),
                                  ("grant_id", "other"), ("agent_id", "other")):
                with pytest.raises(CoreError):
                    runtime.r4_operation_context(operation(req, **{field: value}),
                                                  connection_id="connection", connection_generation=1)
            frame = operation(req)
            with pytest.raises(CoreError):
                runtime.r4_operation_context(frame, connection_id="old-channel", connection_generation=1)
            effective = runtime.r4_operation_context(frame, connection_id="connection", connection_generation=1)
            receipt = await runtime.submit(TurnOperation("turn", "session", "Hello"), effective)
            assert project_r4_turn_receipt(frame, receipt, effective, receipt_revision=1)["stage"] == "SUBMITTED"
            with pytest.raises(CoreError):
                project_r4_turn_receipt(operation(req, credential_epoch=2), receipt,
                                        effective, receipt_revision=1)
            assert len(factory.native.sent) == 1
            with pytest.raises(CoreError):
                await runtime.submit(TurnOperation("legacy-bypass", "session", "Hello"),
                                      replace(context, r4_authority=None))
            clock.advance(60)
            with pytest.raises(CoreError, match="LEASE_EXPIRED"):
                await runtime.install_r4_lease(req, grant(req))
            with pytest.raises(CoreError):
                await runtime.install_r4_lease(replace(req, sent_at_monotonic=clock.now), grant(req))
            assert len(factory.native.sent) == 1
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


@pytest.mark.parametrize('interrupt_allowed', [True, False])
def test_expired_r4_lease_preserves_only_previously_authorized_containment(tmp_path, interrupt_allowed):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        req = await attempt(runtime, clock)
        try:
            actions = ['runtime.open', 'runtime.close', 'turn.submit']
            if interrupt_allowed:
                actions.append('turn.interrupt')
            installed = await runtime.install_r4_lease(req, grant(req, actions))
            await open_session(runtime, installed.context)
            clock.advance(61)  # Expired, still inside the owned shutdown grace.
            with pytest.raises(CoreError, match='LEASE_EXPIRED'):
                runtime.r4_operation_context(operation(req), connection_id='connection', connection_generation=1)
            frame = operation(req, 'interrupt', action='turn.interrupt', expected_turn_id='turn',
                              payload={'reason':'Requested by the agent'})
            for changed in ({**frame, 'connection_generation':2}, {**frame, 'workspace_binding_id':'other'}):
                with pytest.raises(CoreError):
                    runtime.r4_operation_context(changed, connection_id='connection', connection_generation=1)
            with pytest.raises(CoreError):
                runtime.r4_operation_context({**frame, 'containment':True}, connection_id='connection', connection_generation=1)
            if interrupt_allowed:
                context = runtime.r4_operation_context(frame, connection_id='connection', connection_generation=1)
                control = ControlOperation('interrupt','session','interrupt',expected_turn_id='turn',reason='Requested by the agent')
                receipt = await runtime.control(control, context)
                assert receipt.stage == 'SUBMITTED'
                assert await runtime.control(control, context) == receipt
                assert factory.native.sent == [('interrupt', {}, 'interrupt')]
                assert factory.native.targets == ['turn']
            else:
                with pytest.raises(CoreError, match='BINDING_NOT_AUTHORIZED'):
                    runtime.r4_operation_context(frame, connection_id='connection', connection_generation=1)
                assert not factory.native.sent
            close_frame = operation(req, 'close', action='runtime.close', payload={
                'reason':'Requested by the agent', 'drain_seconds':1, 'interrupt_seconds':1})
            context = runtime.r4_operation_context(close_frame, connection_id='connection', connection_generation=1)
            assert (await runtime.close(CloseOperation('close','session','Requested by the agent', ShutdownPolicy(1,1)), context)).stage == 'SUCCEEDED'
            assert factory.native.stopped
            assert await journal.get_receipt(OperationKey('srv','exe','turn')) is None
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


@pytest.mark.parametrize('action', ['approval.decide', 'input.provide'])
@pytest.mark.parametrize('decision', ['decline', 'cancel'])
def test_expired_r4_negative_reply_preserves_request_identity_and_revocation(tmp_path, action, decision):
    from test_runtime import FakeNative, _emit_durable_native_request
    from test_r4_decision_bridge import decision_frame
    class Native(FakeNative):
        def __init__(self):
            super().__init__()
            self.replies = []
        async def reply_native_approval(self, request, reply, response):
            self.replies.append((request, reply, response))
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        factory.native = Native()
        req = await attempt(runtime, clock)
        try:
            installed = await runtime.install_r4_lease(req, grant(req, ['runtime.open','runtime.close',action]))
            await open_session(runtime, installed.context)
            payload = decision_frame(action)['payload']
            payload.update(decision=decision, response_digest=None)
            payload.pop('response', None)
            await _emit_durable_native_request(runtime, factory.native, payload['request'])
            clock.advance(61)
            frame = operation(req, 'negative', action=action, payload=payload)
            context = runtime.r4_operation_context(frame, connection_id='connection', connection_generation=1)
            for denied in ('accept',):
                with pytest.raises(CoreError):
                    await runtime.decide_native_approval(NativeApprovalOperation('positive','session',payload['request'],
                        denied, {'answers':{'q':{'answers':['Answer']}}}), context)
            with pytest.raises(CoreError, match='LEASE_EXPIRED'):
                await runtime.decide_native_approval(NativeApprovalOperation('negative-with-content','session',
                    payload['request'], decision, {'answer':'Productive content'}), context)
            altered = {**payload['request'], 'params':{**payload['request']['params'],'turnId':'another-turn'}}
            with pytest.raises(CoreError, match='NATIVE_REQUEST_NOT_OBSERVED'):
                await runtime.decide_native_approval(NativeApprovalOperation('wrong-turn','session',altered,decision), context)
            native_operation = r4_native_decision_operation(frame)
            receipt = await runtime.decide_native_approval(native_operation, context)
            assert receipt.stage == 'SUBMITTED'
            assert await runtime.decide_native_approval(native_operation, context) == receipt
            assert len(factory.native.replies) == 1 and factory.native.replies[0][1:] == (decision, None)
            await runtime.revoke_r4_lease(context, authorization_revision=2)
            with pytest.raises(CoreError, match='AGENT_REVOKED'):
                runtime.r4_operation_context(frame, connection_id='connection', connection_generation=1)
            assert len(factory.native.replies) == 1
            for operation_id in ('positive','negative-with-content','wrong-turn'):
                assert await journal.get_receipt(OperationKey('srv','exe',operation_id)) is None
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_revocation_during_reconnect_waits_for_actual_generation_and_fences_immediately(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        original_cas = journal.cas_session_lease
        calls = []
        async def held_cas(*args, **kwargs):
            calls.append(kwargs)
            if not kwargs['revoked']:
                entered.set()
                await release.wait()
            return await original_cas(*args, **kwargs)
        try:
            req = await attempt(runtime, clock)
            initial = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, initial.context)
            journal.cas_session_lease = held_cas
            clock.advance(1)
            reconnect = await attempt(runtime, clock, purpose='reconnect', connection_id='new',
                                      connection_generation=2,
                                      scope={**req.scope, 'authorization_revision': 2})
            renewing = asyncio.create_task(runtime.install_r4_lease(reconnect, grant(reconnect)))
            await asyncio.wait_for(entered.wait(), 2)
            revoking = asyncio.create_task(runtime.revoke_r4_lease(initial.context, authorization_revision=3))
            await asyncio.sleep(0)
            assert not revoking.done()
            with pytest.raises(CoreError, match='AGENT_REVOKED'):
                runtime.r4_operation_context(operation(req), connection_id='connection', connection_generation=1)
            release.set()
            with pytest.raises(CoreError):
                await renewing
            revoked = await asyncio.wait_for(revoking, 2)
            assert revoked.acknowledgement['application_stage'] == 'REVOKED'
            assert revoked.acknowledgement['lease_serial'] == 2
            durable = await runtime.persisted_lease(SessionKey('srv', 'exe', 'session'))
            assert durable.revoked and durable.connection_generation == 2 and durable.authorization_revision == 3
            assert len(calls) == 2 and calls[1]['expected_connection_generation'] == 2
            assert await runtime.revoke_r4_lease(initial.context, authorization_revision=3) == revoked
            assert not factory.native.sent
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_pending_renewal_refuses_control_before_locks_and_fences_old_context(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        original_cas = journal.cas_session_lease
        async def held_cas(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original_cas(*args, **kwargs)
        try:
            req = await attempt(runtime, clock)
            initial = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, initial.context)
            journal.cas_session_lease = held_cas
            clock.advance(1)
            renewal = await attempt(runtime, clock, purpose='renew')
            renewing = asyncio.create_task(runtime.install_r4_lease(renewal, grant(renewal,
                ['runtime.open','runtime.close','turn.submit'])))
            await asyncio.wait_for(entered.wait(), 2)
            with pytest.raises(CoreError, match='LEASE_UPDATE_PENDING'):
                await runtime.submit(TurnOperation('productive','session','Hello'), initial.context)
            control = ControlOperation('contain','session','interrupt',expected_turn_id='turn')
            with pytest.raises(CoreError, match='LEASE_UPDATE_PENDING'):
                await asyncio.wait_for(runtime.control(control, initial.context), 2)
            assert not renewing.done() and not factory.native.sent
            release.set()
            current = await asyncio.wait_for(renewing, 2)
            with pytest.raises(CoreError, match='STALE_GENERATION'):
                await runtime.control(replace(control,operation_id='old'), initial.context)
            with pytest.raises(CoreError, match='BINDING_NOT_AUTHORIZED'):
                await runtime.control(replace(control,operation_id='removed'), current.context)
            assert not factory.native.sent
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_lost_renewal_confirmation_recovers_after_old_deadline_without_new_cas(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        original_cas = journal.cas_session_lease
        calls = []
        async def lose_confirmation(*args, **kwargs):
            calls.append(kwargs)
            await original_cas(*args, **kwargs)
            clock.advance(59)
            raise RuntimeError('The lease confirmation was lost.')
        try:
            req = await attempt(runtime, clock)
            initial = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, initial.context)
            journal.cas_session_lease = lose_confirmation
            clock.advance(1)
            renewal = await attempt(runtime, clock, purpose='renew')
            with pytest.raises(RuntimeError, match='confirmation was lost'):
                await runtime.install_r4_lease(renewal, grant(renewal))
            assert clock.now > initial.context.lease_deadline_monotonic
            result = await runtime.install_r4_lease(renewal, grant(renewal))
            assert result.context.lease_deadline_monotonic == renewal.sent_at_monotonic + 59.5
            assert result.context.r4_authority.lease_serial == 2 and len(calls) == 1
            await runtime.submit(TurnOperation('after', 'session', 'Hello'), result.context)
            assert len(factory.native.sent) == 1
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_superseded_nonce_and_mutated_request_cannot_reanchor_authority(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        try:
            old = await attempt(runtime, clock)
            clock.advance(1)
            new = await attempt(runtime, clock)
            assert old.request_id != new.request_id
            with pytest.raises(CoreError):
                await runtime.install_r4_lease(old, grant(old))
            changed = replace(new, scope={**new.scope, 'workspace_binding_id': 'other'})
            with pytest.raises(CoreError):
                await runtime.install_r4_lease(changed, grant(changed))
            with pytest.raises(CoreError):
                await runtime.install_r4_lease(new, None)
            installed = await runtime.install_r4_lease(new, grant(new))
            assert installed.context.lease_deadline_monotonic == new.sent_at_monotonic + 59.5
            assert factory.open_count == 0
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_revocation_reaches_copied_bridge_after_dispatch_thread_wait(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession
    from test_c1_bridge_stubs import harness_session

    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        release = threading.Event()
        entered, sending = asyncio.Event(), asyncio.Event()
        writes = []
        class Connector:
            def send(self, session, command):
                writes.append(command)
        pool = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()
        loop.set_default_executor(pool)
        try:
            req = await attempt(runtime, clock)
            initial = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, initial.context)
            bridge = CopiedAdapterSession(
                Connector(), harness_session(), session_id='session', stream_epoch='epoch',
                context=initial.context, control_executor=pool, force_executor=pool)
            bridge.effect_fence = factory.native.effect_fence
            async def send(*args, **kwargs):
                sending.set()
                await bridge.send(*args, **kwargs)
            factory.native.send = send
            def occupy_worker():
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(5)
            worker = loop.run_in_executor(None, occupy_worker)
            await asyncio.wait_for(entered.wait(), 2)
            submitted = asyncio.create_task(runtime.submit(
                TurnOperation('thread-wait', 'session', 'Hello'), initial.context))
            await asyncio.wait_for(sending.wait(), 2)
            assert not writes and not submitted.done()
            revoking = asyncio.create_task(runtime.revoke_r4_lease(initial.context, authorization_revision=2))
            await asyncio.sleep(0)
            with pytest.raises(CoreError, match='AGENT_REVOKED'):
                runtime.r4_operation_context(operation(req), connection_id='connection', connection_generation=1)
            assert not revoking.done() and not writes
            release.set()
            await worker
            with pytest.raises(CoreError) as denied:
                await submitted
            assert not denied.value.possible_effect and denied.value.retry_safe
            assert (await revoking).acknowledgement['application_stage'] == 'REVOKED'
            assert not writes
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_revocation_fences_copied_factory_after_environment_wait(tmp_path, monkeypatch):
    from tests.regression.test_c4_audit import _pending_open_runtime, _LabAdapter

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def environment(_prepared):
            entered.set()
            await release.wait()
            return {}
        runtime, journal = _pending_open_runtime(tmp_path, monkeypatch, environment=environment)
        _LabAdapter.starts = 0
        try:
            req = await attempt(runtime, None)
            initial = await runtime.install_r4_lease(req, grant(req))
            opening = asyncio.create_task(open_session(runtime, initial.context))
            await asyncio.wait_for(entered.wait(), 2)
            revoking = asyncio.create_task(runtime.revoke_r4_lease(initial.context, authorization_revision=2))
            await asyncio.sleep(0)
            assert not revoking.done() and _LabAdapter.starts == 0
            with pytest.raises(CoreError, match='AGENT_REVOKED'):
                runtime.r4_operation_context(operation(req), connection_id='connection', connection_generation=1)
            release.set()
            with pytest.raises(CoreError) as denied:
                await opening
            assert denied.value.retry_safe and not denied.value.possible_effect
            assert (await revoking).acknowledgement['application_stage'] == 'REVOKED'
            assert _LabAdapter.starts == 0
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_renewal_and_revocation_reach_durable_runtime_cas(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        req = await attempt(runtime, clock)
        try:
            initial = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, initial.context)
            clock.advance(1)
            renewed_request = await attempt(runtime, clock, purpose="reconnect",
                                      connection_id="connection-2", connection_generation=2,
                                      scope={**req.scope, "authorization_revision": 2, "credential_epoch": 2})
            renewed = await runtime.install_r4_lease(renewed_request, grant(renewed_request))
            assert renewed.acknowledgement["application_stage"] == "RENEWED"
            durable = await runtime.persisted_lease(SessionKey("srv", "exe", "session"))
            assert durable.connection_generation == 2 and durable.authorization_revision == 2
            with pytest.raises(CoreError):
                await runtime.submit(TurnOperation("old", "session", "Hello"), initial.context)
            await runtime.submit(TurnOperation("new", "session", "Hello"), renewed.context)
            revoked = await runtime.revoke_r4_lease(renewed.context, authorization_revision=3)
            assert revoked.acknowledgement["application_stage"] == "REVOKED"
            assert (await runtime.persisted_lease(SessionKey("srv", "exe", "session"))).revoked
            assert not revoked.context.allowed_actions
            assert await runtime.revoke_r4_lease(renewed.context, authorization_revision=3) == revoked
            with pytest.raises(CoreError):
                await runtime.submit(TurnOperation("after", "session", "Hello"), renewed.context)
            with pytest.raises(CoreError):
                await runtime.install_r4_lease(renewed_request, grant(renewed_request))
            assert len(factory.native.sent) == 1
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_empty_grant_late_reply_other_boot_and_widening_never_authorize(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        req = await attempt(runtime, clock)
        try:
            for bad in (replace(req, boot_id="previous-boot"),
                        replace(req, sent_at_monotonic=clock.now - 121),
                        replace(req, expected_lease_serial=1)):
                with pytest.raises(CoreError):
                    await runtime.install_r4_lease(bad, grant(bad))
            empty = await runtime.install_r4_lease(req, grant(req, []))
            with pytest.raises(CoreError):
                await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"), empty.context)
            clock.advance(1)
            renewal = await attempt(runtime, clock, purpose="renew")
            with pytest.raises(CoreError):
                await runtime.install_r4_lease(renewal, grant(renewal))
            revoked = await runtime.revoke_r4_lease(empty.context, authorization_revision=2)
            assert revoked.acknowledgement["application_stage"] == "REVOKED"
            assert factory.open_count == 0
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_canceled_renew_waiter_keeps_the_same_cas_producer(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        req = await attempt(runtime, clock)
        original_cas = journal.cas_session_lease
        calls = []
        async def held_cas(*args, **kwargs):
            calls.append(kwargs)
            entered.set()
            await release.wait()
            return await original_cas(*args, **kwargs)
        try:
            initial = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, initial.context)
            journal.cas_session_lease = held_cas
            clock.advance(1)
            renewal = await attempt(runtime, clock, purpose="renew")
            waiting = asyncio.create_task(runtime.install_r4_lease(renewal, grant(renewal)))
            await asyncio.wait_for(entered.wait(), 2)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            with pytest.raises(CoreError, match="LEASE_UPDATE_PENDING"):
                await runtime.submit(TurnOperation("held", "session", "Hello"), initial.context)
            assert len(calls) == 1 and not factory.native.sent
            retry = asyncio.create_task(runtime.install_r4_lease(renewal, grant(renewal)))
            await asyncio.sleep(0)
            assert not retry.done() and len(calls) == 1
            release.set()
            result = await asyncio.wait_for(retry, 2)
            assert result.context.r4_authority.lease_serial == 2
            assert len(calls) == 1
            await runtime.submit(TurnOperation("after", "session", "Hello"), result.context)
            assert len(factory.native.sent) == 1
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_revocation_fences_a_submit_while_its_journal_marker_is_blocked(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        req = await attempt(runtime, clock)
        original_marker = journal.mark_possible_effect
        async def held_marker(key):
            if key.operation_id == "blocked":
                entered.set()
                await release.wait()
            return await original_marker(key)
        try:
            initial = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, initial.context)
            journal.mark_possible_effect = held_marker
            sending = asyncio.create_task(runtime.submit(TurnOperation("blocked", "session", "Hello"), initial.context))
            await asyncio.wait_for(entered.wait(), 2)
            revoke = asyncio.create_task(runtime.revoke_r4_lease(initial.context, authorization_revision=2))
            await asyncio.sleep(0)
            with pytest.raises(CoreError, match="AGENT_REVOKED"):
                runtime.r4_operation_context(operation(req), connection_id="connection", connection_generation=1)
            assert not factory.native.sent and not sending.done()
            release.set()
            with pytest.raises(CoreError) as denied:
                await sending
            assert denied.value.retry_safe and not denied.value.possible_effect
            assert (await revoke).acknowledgement["application_stage"] == "REVOKED"
            assert not factory.native.sent
            assert not (await journal.get_receipt(OperationKey("srv", "exe", "blocked"))).possible_effect
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())
