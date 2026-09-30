"""Restart projection uses a pre-effect hash association, never raw input."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest
from nexus_connector_core import (
    CoreError, ExecutionContext, InstallationCandidate, LaunchIntent, PreparedLaunch,
    Operation, OperationKey, OperationReceipt, installation_ref, r4_submit_intent_hash,
    prepare_r4_receipt_binding, project_r4_bound_receipt, validate_r4_receipt_binding,
    project_r4_open_receipt, project_r4_turn_receipt, project_r4_steer_receipt,
    project_r4_interrupt_receipt, project_r4_close_receipt, project_r4_decision_receipt,
    r4_native_decision_operation,
)
from nexus_connector_core.protocol import intent_hash
from nexus_connector_core.decision_bridge_r4 import native_decision_semantic
from test_r4_receipt_bridge import _frame
from test_r4_decision_bridge import decision_frame


@pytest.mark.parametrize('action', ['runtime.open', 'turn.submit', 'turn.steer', 'turn.interrupt',
                                   'runtime.close', 'approval.decide', 'input.provide'])
def test_binding_recovery_matches_live_projection_for_all_actions(action):
    frame = decision_frame(action) if action in ('approval.decide', 'input.provide') else _frame()
    frame['action'] = action
    context = ExecutionContext(*(frame[k] for k in ('server_id', 'executor_id', 'binding_id', 'agent_id', 'workspace_id')),
                               1, 1, 1, 100, frozenset({action}))
    options = {}
    if action == 'runtime.open':
        candidate = InstallationCandidate('codex_app_server', 'C:/synthetic.exe', 'fp', 'explicit', 'selected')
        frame['payload'] = dict(adapter_id=candidate.adapter_id,
            candidate_ref=installation_ref(candidate.adapter_id, candidate.executable),
            inventory_revision='sha256:' + 'b' * 64, realization_ref='realization',
            realization_revision=1, profile_revision=1, mode='managed')
        prepared = PreparedLaunch(LaunchIntent(context.agent_id, context.workspace_id, candidate.adapter_id),
            candidate, (candidate.executable,), 'C:/workspace', 'C:/workspace', 'root-fp', 'profile-fp', ())
        options = dict(prepared=prepared, stream_epoch='stream')
        semantic = Operation(frame['operation_id'], frame['session_id'], action,
            dict(adapter_id=candidate.adapter_id, root_fingerprint='root-fp', profile_fingerprint='profile-fp', stream_epoch='stream'))
    elif action in ('approval.decide', 'input.provide'):
        operation = r4_native_decision_operation(frame)
        options = dict(applied_operation=operation)
        semantic = native_decision_semantic(operation)
    else:
        frame['payload'] = ({'text': 'PRIVATE_PROMPT_VALUE'} if action in ('turn.submit', 'turn.steer')
                            else {'reason': 'PRIVATE_REASON_VALUE'})
        if action == 'runtime.close':
            frame['payload'].update(drain_seconds=1, interrupt_seconds=1)
        if action == 'turn.steer':
            frame['expected_turn_id'] = 'turn-1'
        semantic = Operation(frame['operation_id'], frame['session_id'], action,
                             frame['payload'], frame.get('expected_turn_id'))
    frame['intent_hash'] = r4_submit_intent_hash(frame)
    binding = prepare_r4_receipt_binding(frame, context, **options)
    saved = json.dumps(binding)
    assert 'PRIVATE_' not in saved and 'private operator response' not in saved
    assert 'payload' not in saved and 'params' not in saved and 'C:/workspace' not in saved
    receipt = OperationReceipt(frame['operation_id'], intent_hash(semantic, context),
                               'SUBMITTED', True, False, frame['session_id'], native_id='native')
    key = OperationKey(context.server_id, context.executor_id, frame['operation_id'])
    recovered = project_r4_bound_receipt(json.loads(saved), receipt, key=key, receipt_revision=1)
    if action == 'runtime.open':
        live = project_r4_open_receipt(frame, receipt, context, prepared, stream_epoch='stream', receipt_revision=1)
    elif action in ('approval.decide', 'input.provide'):
        live = project_r4_decision_receipt(frame, receipt, context, operation, receipt_revision=1)
    else:
        project = {'turn.submit': project_r4_turn_receipt, 'turn.steer': project_r4_steer_receipt,
                   'turn.interrupt': project_r4_interrupt_receipt, 'runtime.close': project_r4_close_receipt}[action]
        live = project(frame, receipt, context, receipt_revision=1)
    assert recovered == live
    for wrong in (replace(receipt, intent_hash=frame['intent_hash']),
                  replace(receipt, operation_id='foreign'), replace(receipt, session_id='foreign')):
        with pytest.raises(CoreError):
            project_r4_bound_receipt(binding, wrong, key=key, receipt_revision=1)
    with pytest.raises(CoreError, match='SCOPE_MISMATCH'):
        project_r4_bound_receipt(binding, receipt, key=replace(key, server_id='foreign'), receipt_revision=1)
    with pytest.raises(CoreError):
        prepare_r4_receipt_binding(frame, replace(context, connection_generation=2), **options)
    damaged = deepcopy(binding)
    damaged['source']['connection_generation'] += 1
    with pytest.raises(CoreError):
        validate_r4_receipt_binding(damaged)


@pytest.mark.parametrize('value', [None, [], {}, {'schema_version': True}, {'source': 'wrong'}])
def test_invalid_binding_is_not_a_receipt(value):
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        validate_r4_receipt_binding(value)


@pytest.mark.parametrize('frame', [None, {}, dict(_frame(), agent_id='foreign')])
def test_live_projection_keeps_original_receipt_identity_on_invalid_envelope(frame):
    context = ExecutionContext('server', 'executor', 'binding', 'agent', 'workspace',
                               1, 1, 1, 100, frozenset({'turn.submit'}))
    receipt = OperationReceipt('original-operation', 'sha256:' + 'a' * 64,
                               'SUBMITTED', True, False, 'session')
    with pytest.raises(CoreError) as rejected:
        project_r4_turn_receipt(frame, receipt, context, receipt_revision=1)
    assert rejected.value.operation_id == 'original-operation'
    assert rejected.value.possible_effect and not rejected.value.retry_safe
