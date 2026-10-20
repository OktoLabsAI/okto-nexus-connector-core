import asyncio
import copy
import json

import pytest
from nexus_connector_core import CoreError, OperationKey, OperationReceipt, SessionKey, project_r4_bound_receipt, r4_submit_intent_hash
from nexus_connector_core.journal import open_journal
from nexus_connector_core import SQLiteOwnedSlotLedger
from nexus_connector_core.startup_refusal_r4 import (
    prepare_r4_startup_refusal, validate_r4_startup_refusal, persist_r4_startup_refusal,
)
from test_r4_receipt_bridge import _frame


def sample():
    frame = _frame()
    frame.update(action='runtime.open', payload=dict(adapter_id='codex_app_server',
        candidate_ref='nexus-install-v1:' + 'a' * 64, inventory_revision='sha256:' + 'b' * 64,
        realization_ref='realization', realization_revision=1, profile_revision=1, mode='managed'))
    frame['intent_hash'] = r4_submit_intent_hash(frame)
    return frame, prepare_r4_startup_refusal(frame)


def key(frame):
    return OperationKey(frame['server_id'], frame['executor_id'], frame['operation_id'])


@pytest.mark.asyncio
async def test_current_connection_refusal_is_durable_without_claiming_native_or_releasing_resources(tmp_path):
    frame, proof = sample()
    path = tmp_path / 'core.db'
    journal = await open_journal(path)
    ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
    sid = SessionKey(frame['server_id'], frame['executor_id'], frame['session_id'])
    try:
        await ledger.reserve_owned_slot(key(frame), frame['session_id'])
        receipt = await persist_r4_startup_refusal(journal, proof)
        assert await journal.get_session_claim(sid) is None
        assert not (await ledger.owned_slot_state(sid)).released
        wire = project_r4_bound_receipt(proof['binding'], receipt, key=key(frame), receipt_revision=1)
        assert wire['intent_hash'] == frame['intent_hash']
        assert wire['connection_generation'] == frame['connection_generation']
        assert wire['stage'] == 'FAILED' and not wire['possible_effect'] and wire['retry_safe']
        assert wire['error_code'] == 'PREPARATION_FAILED'
        assert 'payload' not in json.dumps(proof)
    finally:
        await journal.aclose()
        await ledger.aclose()
    journal = await open_journal(path)
    ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db')
    try:
        assert await persist_r4_startup_refusal(journal, json.loads(json.dumps(proof))) == receipt
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await journal.admit(key(frame), 'native-intent', frame['session_id'],
                                claim_session=True, effect_imminent=True)
        assert not (await ledger.owned_slot_state(sid)).released
    finally:
        await journal.aclose()
        await ledger.aclose()


@pytest.mark.parametrize('stage', ['RECEIVED_DURABLE', 'SUBMISSION_STARTED', 'OUTCOME_UNKNOWN', 'SUCCEEDED'])
@pytest.mark.asyncio
async def test_native_intent_always_wins_over_later_preparation_refusal(tmp_path, stage):
    frame, proof = sample()
    journal = await open_journal(tmp_path / 'core.db')
    try:
        old, _ = await journal.admit(key(frame), 'native-intent', frame['session_id'],
                                    effect_imminent=stage != 'RECEIVED_DURABLE')
        if stage not in ('RECEIVED_DURABLE', 'SUBMISSION_STARTED'):
            old = await journal.record_receipt(key(frame), OperationReceipt(
                frame['operation_id'], 'native-intent', stage, True, False, frame['session_id']))
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await persist_r4_startup_refusal(journal, proof)
        assert await journal.get_receipt(key(frame)) == old
    finally:
        await journal.aclose()


@pytest.mark.parametrize('boundary', ['admit', 'record_receipt'])
@pytest.mark.parametrize('position', ['before', 'after'])
@pytest.mark.asyncio
async def test_commit_observation_loss_recovers_exact_original_refusal(tmp_path, monkeypatch, boundary, position):
    frame, proof = sample()
    path = tmp_path / 'core.db'
    journal = await open_journal(path)
    original = getattr(journal, boundary)
    async def interrupted(*args, **kwargs):
        if position == 'after':
            await original(*args, **kwargs)
        raise OSError('Interrupted observation')
    monkeypatch.setattr(journal, boundary, interrupted)
    try:
        with pytest.raises(OSError):
            await persist_r4_startup_refusal(journal, proof)
    finally:
        await journal.aclose()
    journal = await open_journal(path)
    try:
        receipt = await persist_r4_startup_refusal(journal, proof)
        assert receipt.stage == 'FAILED' and not receipt.possible_effect
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await journal.admit(key(frame), 'native-intent', frame['session_id'], effect_imminent=True)
    finally:
        await journal.aclose()


@pytest.mark.asyncio
async def test_concurrent_native_admission_and_refusal_cannot_both_win(tmp_path):
    frame, proof = sample()
    a, b = await open_journal(tmp_path / 'core.db'), await open_journal(tmp_path / 'core.db')
    try:
        results = await asyncio.gather(persist_r4_startup_refusal(a, proof),
            b.admit(key(frame), 'native-intent', frame['session_id'], effect_imminent=True), return_exceptions=True)
        conflicts = [result for result in results if isinstance(result, CoreError)]
        assert len(conflicts) == 1 and conflicts[0].code == 'OPERATION_CONFLICT'
        receipt = await a.get_receipt(key(frame))
        assert (receipt.intent_hash == 'native-intent') == receipt.possible_effect
    finally:
        await a.aclose()
        await b.aclose()


@pytest.mark.parametrize('field', ['kind', 'grant_id', 'scope', 'source', 'action', 'digest', 'extra', 'schema'])
def test_detached_refusal_rejects_changed_scope_or_corruption(field):
    _, proof = sample()
    proof = copy.deepcopy(proof)
    if field == 'kind': proof['kind'] = 'stopped_session'
    elif field == 'grant_id': proof['grant_id'] = 'other'
    elif field == 'scope': proof['scope']['session_owner_generation'] += 1
    elif field == 'source': proof['binding']['source']['operation_id'] = 'other'
    elif field == 'action': proof['binding']['action'] = 'turn.submit'
    elif field == 'digest': proof['binding']['digest'] = 'sha256:' + '0' * 64
    elif field == 'extra': proof['payload'] = 'untrusted'
    elif field == 'schema': proof['schema_version'] = True
    with pytest.raises(CoreError):
        validate_r4_startup_refusal(proof)


def test_productive_turn_cannot_be_reclassified_as_startup():
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        prepare_r4_startup_refusal(_frame())


@pytest.mark.asyncio
async def test_shared_refusal_port_preserves_the_startup_association(tmp_path):
    from nexus_connector_core import validate_r4_operation_refusal, persist_r4_operation_refusal
    _, proof = sample()
    assert validate_r4_operation_refusal(proof) == proof
    journal = await open_journal(tmp_path / 'core.db')
    try:
        assert await persist_r4_operation_refusal(journal, proof) == await persist_r4_startup_refusal(journal, proof)
    finally:
        await journal.aclose()
