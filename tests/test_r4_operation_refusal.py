import asyncio
import copy
import json

import pytest
from nexus_connector_core import (
    CoreError, OperationKey, SessionKey, prepare_r4_lease_refusal,
    validate_r4_lease_refusal, persist_r4_lease_refusal, project_r4_bound_receipt,
    r4_submit_intent_hash,
)
from nexus_connector_core.journal import open_journal, JournalLimits
from nexus_connector_core.lease_denial import lease_denial_frame
from test_r4_receipt_bridge import _frame
from test_lease_denial import sample


def refusal():
    frame = _frame()
    request = sample()['request']
    request.update({k: frame[k] for k in ('connection_id','connection_generation','grant_id')})
    request.update(scope={k: frame[k] for k in request['scope']}, purpose='renew')
    return frame, prepare_r4_lease_refusal(frame, lease_denial_frame(request))


@pytest.mark.asyncio
async def test_refusal_is_durable_without_a_native_claim_or_effect_and_fences_same_id(tmp_path):
    frame, proof = refusal()
    path = tmp_path / 'core.sqlite3'
    journal = await open_journal(path)
    key = OperationKey(frame['server_id'], frame['executor_id'], frame['operation_id'])
    try:
        receipt = await persist_r4_lease_refusal(journal, proof)
        wire = project_r4_bound_receipt(proof['binding'], receipt, key=key, receipt_revision=1)
        assert wire['intent_hash'] == frame['intent_hash'] and wire['stage'] == 'FAILED'
        assert not wire['possible_effect'] and wire['retry_safe']
        assert wire['error_code'] == 'LEASE_REVALIDATION_REQUIRED'
        assert await journal.get_session_claim(SessionKey(key.server_id,key.executor_id,frame['session_id'])) is None
        assert not (await journal.owned_slot_page()).reservations
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await journal.admit(key, 'native-intent', frame['session_id'])
    finally:
        await journal.aclose()
    journal = await open_journal(path)
    try:
        assert await persist_r4_lease_refusal(journal, json.loads(json.dumps(proof))) == receipt
        assert 'Hello' not in json.dumps(proof) and 'payload' not in json.dumps(proof)
    finally:
        await journal.aclose()


@pytest.mark.parametrize('native_first', [False, True])
@pytest.mark.asyncio
async def test_cross_journal_conflict_never_relabels_existing_native_work(tmp_path, native_first):
    frame, proof = refusal()
    first, second = await open_journal(tmp_path / 'core.db'), await open_journal(tmp_path / 'core.db')
    key = OperationKey(frame['server_id'],frame['executor_id'],frame['operation_id'])
    try:
        if native_first:
            await first.admit(key, 'native-intent', frame['session_id'], effect_imminent=True)
            with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
                await persist_r4_lease_refusal(second, proof)
            current = await second.get_receipt(key)
            assert current.possible_effect and current.intent_hash == 'native-intent'
        else:
            results = await asyncio.gather(persist_r4_lease_refusal(first, proof),
                second.admit(key, 'native-intent', frame['session_id'], effect_imminent=True), return_exceptions=True)
            assert sum(isinstance(result, CoreError) for result in results) == 1
            current = await first.get_receipt(key)
            assert (current.intent_hash == 'native-intent') == current.possible_effect
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_crash_after_refusal_admission_recovers_without_native_authority(tmp_path):
    frame, proof = refusal()
    key = OperationKey(frame['server_id'], frame['executor_id'], frame['operation_id'])
    journal = await open_journal(tmp_path / 'core.db')
    await journal.admit(key, proof['binding']['core_intent_hash'], frame['session_id'])
    await journal.aclose()
    journal = await open_journal(tmp_path / 'core.db')
    try:
        assert (await journal.get_receipt(key)).stage == 'RECEIVED_DURABLE'
        receipt = await persist_r4_lease_refusal(journal, proof)
        assert receipt.stage == 'FAILED' and not receipt.possible_effect
    finally:
        await journal.aclose()


@pytest.mark.parametrize('tamper', ['session','generation','scope','hash','action','grant','extra'])
def test_refusal_binding_rejects_changed_provenance(tamper):
    _, proof = refusal()
    changed = copy.deepcopy(proof)
    if tamper == 'session': changed['binding']['source']['session_id'] = 'other'
    elif tamper == 'generation': changed['denial']['request']['connection_generation'] += 1
    elif tamper == 'scope': changed['scope']['credential_epoch'] += 1
    elif tamper == 'hash': changed['binding']['core_intent_hash'] = 'sha256:' + 'f' * 64
    elif tamper == 'action': changed['binding']['action'] = 'runtime.close'
    elif tamper == 'grant': changed['grant_id'] = 'other'
    else: changed['secret'] = 'forbidden'
    with pytest.raises(CoreError): validate_r4_lease_refusal(changed)


@pytest.mark.parametrize('action', ['turn.interrupt','runtime.close'])
def test_containment_is_not_reclassified_as_productive_refusal(action):
    frame, proof = refusal()
    frame['action'] = action
    frame['payload'] = {'reason':'Contain this session'}
    if action == 'runtime.close': frame['payload'].update(drain_seconds=1,interrupt_seconds=1)
    frame['intent_hash'] = r4_submit_intent_hash(frame)
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        prepare_r4_lease_refusal(frame, proof['denial'])


@pytest.mark.asyncio
async def test_refusal_never_consumes_containment_quota(tmp_path):
    frame, proof = refusal()
    journal = await open_journal(tmp_path / 'core.db', limits=JournalLimits(max_operation_rows=2,reserved_operation_rows=1))
    try:
        await persist_r4_lease_refusal(journal, proof)
        another = dict(frame, operation_id='other')
        another['intent_hash'] = r4_submit_intent_hash(another)
        other_proof = prepare_r4_lease_refusal(another, proof['denial'])
        with pytest.raises(CoreError, match='JOURNAL_FULL'):
            await persist_r4_lease_refusal(journal, other_proof)
        await journal.admit(OperationKey(frame['server_id'],frame['executor_id'],'close'),
                            'containment', frame['session_id'], critical=True)
    finally:
        await journal.aclose()
