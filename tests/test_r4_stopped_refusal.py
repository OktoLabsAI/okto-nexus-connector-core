import copy
import json

import pytest
from nexus_connector_core import (
    CoreError, OperationKey, SessionKey, prepare_r4_stopped_refusal,
    validate_r4_operation_refusal, persist_r4_operation_refusal,
    project_r4_bound_receipt, r4_submit_intent_hash,
)
from nexus_connector_core.journal import open_journal
from test_r4_operation_refusal import refusal


def stopped(code='LEASE_EXPIRED'):
    frame, denied = refusal()
    args = dict(scope=denied['scope'], connection_id=frame['connection_id'],
        connection_generation=frame['connection_generation'], error_code=code)
    return frame, args, prepare_r4_stopped_refusal(frame, **args)


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['LEASE_EXPIRED', 'LEASE_REVALIDATION_REQUIRED'])
@pytest.mark.parametrize('crash_after_admission', [False, True])
async def test_stopped_refusal_survives_restart_without_native_effect(tmp_path, code, crash_after_admission):
    frame, _, proof = stopped(code)
    path = tmp_path/'journal.db'
    key = OperationKey(frame['server_id'], frame['executor_id'], frame['operation_id'])
    journal = await open_journal(path)
    if crash_after_admission:
        await journal.admit(key, proof['binding']['core_intent_hash'], frame['session_id'])
        await journal.aclose()
        journal = await open_journal(path)
    try:
        receipt = await persist_r4_operation_refusal(journal, json.loads(json.dumps(proof)))
        assert receipt.stage == 'FAILED' and not receipt.possible_effect and receipt.retry_safe
        assert receipt.error_code == code
        assert await persist_r4_operation_refusal(journal, proof) == receipt
        wire = project_r4_bound_receipt(proof['binding'], receipt, key=key, receipt_revision=1)
        assert wire['intent_hash'] == frame['intent_hash']
        assert await journal.get_session_claim(SessionKey(key.server_id, key.executor_id, frame['session_id'])) is None
        assert not (await journal.owned_slot_page()).reservations
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await journal.admit(key, 'native-intent', frame['session_id'], effect_imminent=True)
        assert 'Hello' not in json.dumps(proof) and 'payload' not in json.dumps(proof)
    finally:
        await journal.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('possible_effect', [False, True])
async def test_refusal_cannot_relabel_an_existing_native_operation(tmp_path, possible_effect):
    frame, _, proof = stopped()
    key = OperationKey(frame['server_id'], frame['executor_id'], frame['operation_id'])
    journal = await open_journal(tmp_path/'journal.db')
    try:
        original, _ = await journal.admit(key, 'native-intent', frame['session_id'], effect_imminent=possible_effect)
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await persist_r4_operation_refusal(journal, proof)
        assert await journal.get_receipt(key) == original
    finally:
        await journal.aclose()


@pytest.mark.parametrize('field', ['session_id','agent_id','workspace_id','binding_id',
    'session_owner_generation','configuration_revision','credential_epoch','connection_id','connection_generation'])
def test_stopped_fence_cannot_refuse_another_scope(field):
    frame, args, _ = stopped()
    args = copy.deepcopy(args)
    target = args if field.startswith('connection_') else args['scope']
    target[field] = target[field] + 1 if type(target[field]) is int else 'other'
    with pytest.raises(CoreError, match='SCOPE_MISMATCH'):
        prepare_r4_stopped_refusal(frame, **args)


@pytest.mark.parametrize('action', ['turn.interrupt', 'runtime.close'])
def test_containment_never_becomes_a_productive_refusal(action):
    frame, args, _ = stopped()
    frame['action'], frame['payload'] = action, {'reason':'Stop'}
    if action == 'runtime.close':
        frame['payload'].update(drain_seconds=1,interrupt_seconds=1)
    frame['intent_hash'] = r4_submit_intent_hash(frame)
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        prepare_r4_stopped_refusal(frame, **args)


@pytest.mark.parametrize('field,value', [('error_code','SUCCEEDED'), ('kind','lease.denied'),
    ('grant_id','changed'), ('schema_version',True), ('secret','not-allowed')])
def test_stored_refusal_is_strict_and_tamper_evident(field, value):
    _, _, proof = stopped()
    proof[field] = value
    with pytest.raises(CoreError):
        validate_r4_operation_refusal(proof)
