"""A replacement host must fence a delayed opening, not infer no effect."""
import asyncio
import copy
import json
from hashlib import sha256

import pytest

from nexus_connector_core import (
    CoreError, OperationKey, OperationReceipt, SessionKey,
    prepare_r4_preopen_refusal, validate_r4_preopen_refusal,
    persist_r4_preopen_refusal, project_r4_bound_receipt,
)
from nexus_connector_core.journal import JournalLimits, open_journal
from nexus_connector_core.protocol import canonical_json
from test_r4_receipt_bridge import _frame


def proof(*, bound=False):
    frame = _frame()
    source = {k: frame[k] for k in ('protocol_major', 'contract_revision', 'server_id', 'executor_id',
        'binding_id', 'agent_id', 'session_id', 'connection_id', 'connection_generation', 'operation_id', 'intent_hash')}
    prior = None
    if bound:
        body = dict(schema_version=1, source=source, action='runtime.open', core_intent_hash='sha256:' + 'a' * 64)
        prior = dict(body, digest='sha256:' + sha256(canonical_json(body)).hexdigest())
    return prepare_r4_preopen_refusal(source, session_owner_generation=frame['session_owner_generation'],
        recovery={'connection_id': 'replacement', 'connection_generation': source['connection_generation'] + 1},
        prior_binding=prior)


def key(value):
    source = value['source']
    return OperationKey(source['server_id'], source['executor_id'], source['operation_id'])


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.asyncio
async def test_preopen_fence_survives_restart_without_claiming_or_executing(tmp_path, bound):
    value = proof(bound=bound)
    path = tmp_path / 'core.db'
    journal = await open_journal(path)
    try:
        receipt = await persist_r4_preopen_refusal(journal, value)
        wire = project_r4_bound_receipt(value['binding'], receipt, key=key(value), receipt_revision=1)
        assert wire['intent_hash'] == value['source']['intent_hash']
        assert wire['stage'] == 'FAILED' and not wire['possible_effect'] and wire['retry_safe']
        assert wire['error_code'] == 'PRE_EXECUTION_FENCED'
        assert await journal.get_session_claim(SessionKey(key(value).server_id, key(value).executor_id,
                                                        value['source']['session_id'])) is None
        assert not (await journal.owned_slot_page()).reservations
    finally:
        await journal.aclose()
    journal = await open_journal(path)
    try:
        assert await persist_r4_preopen_refusal(journal, json.loads(json.dumps(value))) == receipt
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await journal.admit(key(value), 'sha256:' + 'a' * 64, value['source']['session_id'],
                                claim_session=True, effect_imminent=True)
        assert await journal.get_receipt(key(value)) == receipt
    finally:
        await journal.aclose()


@pytest.mark.parametrize('stage', ['RECEIVED_DURABLE', 'SUBMISSION_STARTED', 'OUTCOME_UNKNOWN', 'SUCCEEDED'])
@pytest.mark.asyncio
async def test_existing_original_intent_is_never_reclassified_as_unstarted(tmp_path, stage):
    value = proof(bound=True)
    journal = await open_journal(tmp_path / 'core.db')
    try:
        digest, sid = value['prior_binding']['core_intent_hash'], value['source']['session_id']
        old, _ = await journal.admit(key(value), digest, sid, effect_imminent=stage != 'RECEIVED_DURABLE')
        if stage not in ('RECEIVED_DURABLE', 'SUBMISSION_STARTED'):
            old = await journal.record_receipt(key(value), OperationReceipt(
                key(value).operation_id, digest, stage, True, False, sid))
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await persist_r4_preopen_refusal(journal, value)
        assert await journal.get_receipt(key(value)) == old
    finally:
        await journal.aclose()


@pytest.mark.parametrize('boundary', ['admit', 'record_receipt'])
@pytest.mark.parametrize('position', ['before_commit', 'after_commit'])
@pytest.mark.asyncio
async def test_preopen_fence_commit_reply_loss_finishes_same_association(tmp_path, monkeypatch, boundary, position):
    value = proof(bound=True)
    persisted = tmp_path / 'association.json'
    persisted.write_text(json.dumps(value))
    journal = await open_journal(tmp_path / 'core.db')
    original = getattr(journal, boundary)
    async def cut(*args, **kwargs):
        if position == 'after_commit':
            await original(*args, **kwargs)
        raise OSError('Synthetic interrupted journal observation')
    monkeypatch.setattr(journal, boundary, cut)
    try:
        with pytest.raises(OSError):
            await persist_r4_preopen_refusal(journal, value)
    finally:
        await journal.aclose()
    journal = await open_journal(tmp_path / 'core.db')
    try:
        receipt = await persist_r4_preopen_refusal(journal, json.loads(persisted.read_text()))
        assert receipt.stage == 'FAILED' and not receipt.possible_effect
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await journal.admit(key(value), value['prior_binding']['core_intent_hash'], value['source']['session_id'])
    finally:
        await journal.aclose()


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.asyncio
async def test_two_journal_owners_cannot_both_fence_and_admit_original(tmp_path, bound):
    value = proof(bound=bound)
    first, second = await open_journal(tmp_path / 'core.db'), await open_journal(tmp_path / 'core.db')
    try:
        results = await asyncio.gather(persist_r4_preopen_refusal(first, value),
            second.admit(key(value), 'sha256:' + 'a' * 64, value['source']['session_id'], effect_imminent=True),
            return_exceptions=True)
        conflicts = [item for item in results if isinstance(item, CoreError)]
        assert len(conflicts) == 1 and conflicts[0].code == 'OPERATION_CONFLICT'
        current = await first.get_receipt(key(value))
        if current.intent_hash == value['binding']['core_intent_hash']:
            assert current.stage == 'FAILED' and not current.possible_effect
        else:
            assert current.intent_hash == 'sha256:' + 'a' * 64 and current.possible_effect
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.parametrize('change', ['same_generation', 'older_generation', 'same_connection', 'bool_generation',
    'extra', 'source', 'owner', 'prior_source', 'prior_action', 'hash'])
def test_preopen_refusal_rejects_changed_scope_or_stale_owner(change):
    value = copy.deepcopy(proof(bound=True))
    if change == 'same_generation': value['recovery']['connection_generation'] = value['source']['connection_generation']
    elif change == 'older_generation': value['recovery']['connection_generation'] = 0
    elif change == 'same_connection': value['recovery']['connection_id'] = value['source']['connection_id']
    elif change == 'bool_generation': value['recovery']['connection_generation'] = True
    elif change == 'extra': value['payload'] = 'not allowed'
    elif change == 'source': value['source']['executor_id'] = 'other'
    elif change == 'owner': value['session_owner_generation'] += 1
    elif change == 'prior_source': value['prior_binding']['source']['operation_id'] = 'other'
    elif change == 'prior_action': value['prior_binding']['action'] = 'turn.submit'
    else: value['binding']['core_intent_hash'] = 'sha256:' + 'b' * 64
    with pytest.raises(CoreError):
        validate_r4_preopen_refusal(value)


@pytest.mark.asyncio
async def test_preopen_refusal_preserves_reserved_containment_quota(tmp_path):
    value = proof()
    journal = await open_journal(tmp_path / 'core.db',
        limits=JournalLimits(max_operation_rows=2, reserved_operation_rows=1))
    try:
        await persist_r4_preopen_refusal(journal, value)
        source = dict(value['source'], operation_id='other')
        other = prepare_r4_preopen_refusal(source, session_owner_generation=value['session_owner_generation'],
                                          recovery=value['recovery'])
        with pytest.raises(CoreError, match='JOURNAL_FULL'):
            await persist_r4_preopen_refusal(journal, other)
        await journal.admit(OperationKey(key(value).server_id, key(value).executor_id, 'close'),
                            'containment', source['session_id'], critical=True)
    finally:
        await journal.aclose()


def report():
    value = proof(bound=True)
    source = value['source']
    fact = OperationReceipt(source['operation_id'], value['binding']['core_intent_hash'],
        'FAILED', False, True, source['session_id'], error_code='PRE_EXECUTION_FENCED')
    return dict(refusal=value, receipt=project_r4_bound_receipt(value['binding'], fact,
        key=key(value), receipt_revision=1), capacity=None, slot=None)


def reconciliation(item):
    source, recovery = item['refusal']['source'], item['refusal']['recovery']
    return {k: source[k] for k in ('protocol_major', 'contract_revision', 'server_id', 'executor_id')} | recovery | dict(
        type='reconcile.report', reconcile_id='recovery', cursor=None, next_cursor=None, complete=True,
        receipts=[], claims=[], ownership_facts=[], stream_watermarks=[], preopen_refusals=[item])


def test_preopen_report_roundtrip_preserves_refusal_and_prior_binding():
    from nexus_connector_core import decode_r4_frame, encode_r4_frame
    from nexus_connector_core.preopen_refusal_r4 import validate_r4_preopen_report
    item = report()
    assert validate_r4_preopen_report(item) == item
    frame = reconciliation(item)
    assert decode_r4_frame(encode_r4_frame(frame)) == frame
    # A later authenticated recovery cycle can finish the original proof;
    # it cannot change the immutable Core intent after a lost acknowledgment.
    frame['connection_generation'] += 1
    frame['connection_id'] = 'later-replacement'
    assert decode_r4_frame(encode_r4_frame(frame)) == frame


@pytest.mark.parametrize('change', ['effect', 'retry', 'revision', 'native', 'receipt_hash',
    'extra', 'slot_owner', 'unreleased_slot', 'duplicate', 'wrong_executor', 'earlier_generation', 'same_generation_other_owner'])
def test_preopen_report_codec_rejects_unproved_or_mismatched_facts(change):
    from nexus_connector_core import encode_r4_frame
    item = report()
    frame = reconciliation(item)
    if change == 'effect': item['receipt']['possible_effect'] = True
    elif change == 'retry': item['receipt']['retry_safe'] = False
    elif change == 'revision': item['receipt']['receipt_revision'] = 2
    elif change == 'native': item['receipt']['native_id'] = 'already-running'
    elif change == 'receipt_hash': item['receipt']['intent_hash'] = 'sha256:' + 'f' * 64
    elif change == 'extra': item['credential'] = 'forbidden'
    elif change in ('slot_owner', 'unreleased_slot'):
        item['slot'] = {k: item['refusal']['source'][k] for k in ('server_id', 'executor_id', 'session_id')} | dict(
            opening_operation_id='other' if change == 'slot_owner' else key(item['refusal']).operation_id,
            released=change != 'unreleased_slot')
    elif change == 'duplicate': frame['preopen_refusals'].append(item)
    elif change == 'wrong_executor': frame['executor_id'] = 'other'
    elif change == 'earlier_generation': frame['connection_generation'] -= 1
    else: frame['connection_id'] = 'not-the-fence-owner'
    with pytest.raises(CoreError):
        encode_r4_frame(frame)


@pytest.mark.parametrize('change', [None, 'session', 'generation', 'opening_hash', 'state', 'missing_slot'])
def test_preopen_capacity_release_matches_exact_original_consumption(change):
    from dataclasses import replace
    from nexus_connector_core import CapacityReservation
    from nexus_connector_core.preopen_refusal_r4 import validate_r4_preopen_report
    from test_capacity_contract import request, consumed
    item = report()
    source = item['refusal']['source']
    req = request('new_session')
    scope = replace(req.scope, **{k: source[k] for k in ('server_id', 'executor_id', 'binding_id', 'agent_id',
        'session_id', 'connection_generation')}, session_owner_generation=item['refusal']['session_owner_generation'])
    req = replace(req, scope=scope)
    consumption = replace(consumed('new_session'), opening_operation_id=source['operation_id'], opening_intent_hash=source['intent_hash'])
    capacity = CapacityReservation('original-ticket', req, 'RELEASED', 2, 0, consumption)
    item['capacity'] = capacity.to_dict()
    item['slot'] = {k: source[k] for k in ('server_id', 'executor_id', 'session_id')} | dict(
        opening_operation_id='capacity:original-ticket', released=True)
    if change == 'session': item['capacity']['request']['scope']['session_id'] = 'other'
    elif change == 'generation': item['capacity']['request']['scope']['connection_generation'] += 1
    elif change == 'opening_hash': item['capacity']['consumption']['opening_intent_hash'] = 'sha256:' + 'd' * 64
    elif change == 'state': item['capacity']['state'] = 'CONSUMED'
    elif change == 'missing_slot': item['slot'] = None
    if change is None:
        assert validate_r4_preopen_report(item) == item
    else:
        with pytest.raises(CoreError):
            validate_r4_preopen_report(item)
