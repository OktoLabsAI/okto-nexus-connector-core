"""Close policy applies to one owned session and outlives its waiters."""

import asyncio
from dataclasses import replace
import math

import pytest

from nexus_connector_core import (
    CloseOperation, ControlOperation, CoreError, LaunchIntent, OpenOperation,
    Operation, OperationKey, OperationReceipt, SessionKey, ShutdownPolicy, TurnOperation,
    intent_hash, project_r4_close_receipt, r4_close_operation, r4_submit_intent_hash,
)
from test_runtime import context, make_runtime, FakeNative
from test_r4_receipt_bridge import _frame


async def opened(runtime, session='session'):
    authority = context()
    prepared = await runtime.prepare(LaunchIntent('agent','ws','codex_app_server'), authority)
    await runtime.open(OpenOperation('open-'+session, session, 'epoch', prepared), authority)
    return authority


@pytest.mark.parametrize('policy', [
    ShutdownPolicy(-1,1), ShutdownPolicy(31,1), ShutdownPolicy(1,16),
    ShutdownPolicy(True,1), ShutdownPolicy(1,'1'), ShutdownPolicy(math.nan,1),
    ShutdownPolicy(1,math.inf), ShutdownPolicy(10**1000,1), {},
])
def test_invalid_close_policy_has_no_journal_or_native_effect(tmp_path, policy):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        try:
            with pytest.raises(CoreError, match='VALIDATION_ERROR'):
                await runtime.close(CloseOperation('close','session','Stop',policy), context())
            assert await journal.get_receipt(OperationKey('srv','exe','close')) is None
            assert not factory.native.stopped
        finally:
            await runtime.shutdown(ShutdownPolicy(0,0))
            journal.close()
    asyncio.run(run())


def test_r4_policy_is_required_projected_and_hashed():
    frame = _frame()
    frame.update(action='runtime.close', payload=dict(reason='',drain_seconds=2,interrupt_seconds=1))
    frame['intent_hash'] = r4_submit_intent_hash(frame)
    operation = r4_close_operation(frame)
    assert operation.policy == ShutdownPolicy(2,1) and operation.reason == ''
    authority = replace(context(), server_id=frame['server_id'], executor_id=frame['executor_id'],
        binding_id=frame['binding_id'], agent_id=frame['agent_id'], workspace_id=frame['workspace_id'],
        configuration_revision=frame['configuration_revision'],
        connection_generation=frame['connection_generation'])
    semantic = Operation(frame['operation_id'], frame['session_id'], 'runtime.close', frame['payload'])
    receipt = OperationReceipt(frame['operation_id'], intent_hash(semantic,authority), 'SUBMITTED',True,False,frame['session_id'])
    assert project_r4_close_receipt(frame,receipt,authority,receipt_revision=1)['intent_hash'] == frame['intent_hash']
    changed = {**frame, 'payload':{**frame['payload'],'drain_seconds':3}}
    changed['intent_hash'] = r4_submit_intent_hash(changed)
    assert changed['intent_hash'] != frame['intent_hash']
    with pytest.raises(CoreError,match='OPERATION_CONFLICT'):
        project_r4_close_receipt(changed,receipt,authority,receipt_revision=1)
    missing = {**frame, 'payload':{'reason':''}}
    missing['intent_hash'] = r4_submit_intent_hash(missing)
    with pytest.raises(CoreError,match='VALIDATION_ERROR'):
        r4_close_operation(missing)


@pytest.mark.parametrize('reason', ['', 'x'*1024])
def test_full_reason_range_and_legacy_hash_preservation(tmp_path, reason):
    async def run():
        runtime, journal, _ = make_runtime(tmp_path)
        try:
            authority = await opened(runtime)
            interrupt = await runtime.control(ControlOperation('interrupt','session','interrupt',reason=reason),authority)
            assert interrupt.intent_hash == intent_hash(Operation('interrupt','session','turn.interrupt',{'reason':reason}),authority)
            # An omitted policy keeps the legacy close semantic hash unchanged.
            closed = await runtime.close(CloseOperation('close','session',reason),authority)
            assert closed.intent_hash == intent_hash(Operation('close','session','runtime.close',{'reason':reason}),authority)
        finally:
            await runtime.shutdown(ShutdownPolicy(0,0))
            journal.close()
    asyncio.run(run())


def test_policy_drains_then_interrupts_without_admitting_new_work(tmp_path):
    async def run():
        runtime,journal,factory = make_runtime(tmp_path)
        authority = await opened(runtime)
        sending, release, interrupted = asyncio.Event(), asyncio.Event(), asyncio.Event()
        native = factory.native
        native.active_turn = lambda: not release.is_set()
        original = native.send
        async def send(verb,payload,operation_id,*,expected_turn_id=None):
            if verb == 'send_turn':
                sending.set()
                await release.wait()
            if verb == 'interrupt': interrupted.set()
            await original(verb,payload,operation_id,expected_turn_id=expected_turn_id)
        native.send = send
        pending = asyncio.create_task(runtime.submit(TurnOperation('turn','session','Hello'),authority))
        close = None
        try:
            await asyncio.wait_for(sending.wait(),2)
            close = asyncio.create_task(runtime.close(CloseOperation('close','session','Stop',ShutdownPolicy(.05,1)),authority))
            await asyncio.wait_for(interrupted.wait(),2)
            assert not close.done() and not native.stopped
            with pytest.raises(CoreError,match='SESSION_CLOSING'):
                await runtime.submit(TurnOperation('new','session','New work'),authority)
            assert await journal.get_receipt(OperationKey('srv','exe','new')) is None
            release.set()
            await pending
            assert (await close).stage == 'SUBMITTED'
            assert sum(verb == 'interrupt' for verb,_,_ in native.sent) == 1
        finally:
            release.set()
            await pending
            if close is not None: await asyncio.gather(close,return_exceptions=True)
            await runtime.shutdown(ShutdownPolicy(0,0))
            journal.close()
    asyncio.run(run())


def test_cancelled_waiter_keeps_one_close_producer_and_receipt(tmp_path):
    async def run():
        runtime,journal,factory = make_runtime(tmp_path)
        authority = await opened(runtime)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        original = factory.native.close
        async def close_native():
            calls.append('close')
            entered.set()
            await release.wait()
            return await original()
        factory.native.close = close_native
        operation = CloseOperation('close','session','Stop',ShutdownPolicy(1,1))
        waiter = asyncio.create_task(runtime.close(operation,authority))
        try:
            await asyncio.wait_for(entered.wait(),2)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError): await waiter
            with pytest.raises(CoreError,match='OPERATION_CONFLICT'):
                await runtime.close(replace(operation,policy=ShutdownPolicy(2,1)),authority)
            with pytest.raises(CoreError,match='SESSION_CLOSING'):
                await asyncio.wait_for(runtime.close(CloseOperation('legacy-close','session'),authority),1)
            assert calls == ['close'] and not factory.native.stopped
            second = asyncio.create_task(runtime.close(operation,authority))
            release.set()
            receipt = await asyncio.wait_for(second,2)
            assert receipt.stage == 'SUBMITTED'
            assert await runtime.close(operation,authority) == receipt
            assert calls == ['close']
        finally:
            release.set()
            await asyncio.gather(waiter,return_exceptions=True)
            await runtime.shutdown(ShutdownPolicy(0,0))
            journal.close()
    asyncio.run(run())


def test_force_deadline_does_not_wait_for_normal_write_and_unknown_is_recoverable(tmp_path):
    async def run():
        runtime,journal,factory = make_runtime(tmp_path)
        authority = await opened(runtime)
        entered,release,forced = asyncio.Event(),asyncio.Event(),asyncio.Event()
        native=factory.native
        native.active_turn=lambda: True
        original_send,original_close=native.send,native.close
        async def send(verb,payload,operation_id,*,expected_turn_id=None):
            if verb=='send_turn':
                entered.set()
                await release.wait()
            await original_send(verb,payload,operation_id,expected_turn_id=expected_turn_id)
        async def force(): forced.set()
        async def close_native():
            await original_close()
            return 'forced'
        native.send,native.force_stop,native.close=send,force,close_native
        pending=asyncio.create_task(runtime.submit(TurnOperation('turn','session','Hello'),authority))
        operation=CloseOperation('close','session','Stop',ShutdownPolicy(.03,.03))
        try:
            await asyncio.wait_for(entered.wait(),2)
            with pytest.raises(CoreError,match='OUTCOME_UNKNOWN') as error:
                await runtime.close(operation,authority)
            assert error.value.possible_effect and not error.value.retry_safe
            await asyncio.wait_for(forced.wait(),2)
            assert not release.is_set() and not native.stopped
            assert (await runtime.inspect(SessionKey('srv','exe','session'))).ownership == 'owned'
            assert (await journal.get_receipt(OperationKey('srv','exe','close'))).stage == 'SUBMISSION_STARTED'
            release.set()
            await pending
            async def durable():
                while True:
                    receipt=await journal.get_receipt(OperationKey('srv','exe','close'))
                    if receipt.stage=='SUBMITTED': return receipt
                    await asyncio.sleep(.01)
            receipt=await asyncio.wait_for(durable(),2)
            assert await runtime.close(operation,authority)==receipt
        finally:
            release.set()
            await pending
            await runtime.shutdown(ShutdownPolicy(0,0))
            journal.close()
    asyncio.run(run())


def test_policy_closes_only_its_session(tmp_path):
    async def run():
        runtime,journal,factory=make_runtime(tmp_path)
        natives={}
        async def factory_open(prepared,session_id,authority,*,stream_epoch):
            natives[session_id]=FakeNative()
            return natives[session_id]
        factory.open=factory_open
        try:
            authority=await opened(runtime,'one')
            await opened(runtime,'two')
            receipt=await runtime.close(CloseOperation('close-one','one','',ShutdownPolicy(1,1)),authority)
            assert receipt.stage=='SUBMITTED'
            assert natives['one'].stopped and not natives['two'].stopped
            assert (await runtime.submit(TurnOperation('turn-two','two','Hello'),authority)).stage=='SUBMITTED'
        finally:
            await runtime.shutdown(ShutdownPolicy(0,0))
            journal.close()
    asyncio.run(run())
