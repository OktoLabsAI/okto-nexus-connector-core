"""Non-secret, pre-effect association of Core and R4 operation semantics.

The host persists this record before calling the runtime. It grants no execution
authority and contains no prompt, input response, native request or credential.
Its digest detects corruption; it is not a signature from an untrusted peer.
"""
import hashlib
import re

from .models import CoreError, NativeApprovalOperation, Operation, OperationKey, OperationReceipt, PreparedLaunch
from .harness_configuration import harness_settings_dict
from .protocol import canonical_json, intent_hash, strict_json
from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .installation import effective_installation_ref
from .close_operation import close_operation_semantic, r4_close_operation
from .decision_bridge_r4 import native_decision_semantic, r4_native_decision_operation
from .receipt_bridge_r4 import _checked_source


_SOURCE = ('protocol_major', 'contract_revision', 'server_id', 'executor_id',
           'binding_id', 'agent_id', 'session_id', 'connection_id',
           'connection_generation', 'operation_id', 'intent_hash')
_ACTIONS = {'runtime.open', 'turn.submit', 'turn.steer', 'turn.interrupt',
            'runtime.close', 'approval.decide', 'input.provide'}


def prepare_r4_receipt_binding(submit_frame, context, *, prepared=None,
                               stream_epoch=None, applied_operation=None):
    """Validate and hash the exact local semantic before its native effect."""
    try:
        frame = _checked_source(submit_frame, context, action=submit_frame.get('action'))
        action, payload = frame['action'], frame['payload']
        if action == 'runtime.open':
            if (not isinstance(prepared, PreparedLaunch) or not isinstance(stream_epoch, str) or
                    not stream_epoch or prepared.intent.agent_id != context.agent_id or
                    prepared.intent.workspace_id != context.workspace_id or
                    prepared.intent.adapter_id != payload['adapter_id'] or
                    prepared.intent.mode != payload['mode'] or prepared.intent.model != payload.get('model') or
                    harness_settings_dict(prepared.intent.harness_settings) != payload.get('harness_settings', {}) or
                    effective_installation_ref(prepared.candidate) != payload['candidate_ref']):
                raise CoreError('PROFILE_DRIFT', 'r4_receipt_binding')
            semantic = Operation(frame['operation_id'], frame['session_id'], action,
                {'adapter_id': prepared.intent.adapter_id, 'profile_fingerprint': prepared.profile_fingerprint,
                 'root_fingerprint': prepared.root_fingerprint, 'stream_epoch': stream_epoch})
        elif action == 'runtime.close':
            semantic = close_operation_semantic(r4_close_operation(frame))
        elif action in ('approval.decide', 'input.provide'):
            if not isinstance(applied_operation, NativeApprovalOperation):
                raise CoreError('VALIDATION_ERROR', 'r4_receipt_binding')
            expected = r4_native_decision_operation(frame,
                resolved_response=applied_operation.operator_response if payload.get('response_ref') else None)
            if expected != applied_operation:
                raise CoreError('OPERATION_CONFLICT', 'r4_receipt_binding')
            semantic = native_decision_semantic(applied_operation)
        else:
            key = 'text' if action in ('turn.submit', 'turn.steer') else 'reason'
            semantic = Operation(frame['operation_id'], frame['session_id'], action,
                                 {key: payload[key]}, frame.get('expected_turn_id'))
        body = dict(schema_version=1, action=action, core_intent_hash=intent_hash(semantic, context),
                    source={k: frame[k] for k in _SOURCE})
        return validate_r4_receipt_binding(body | {'digest': _digest(body)})
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_receipt_binding') from error


def _digest(value):
    return 'sha256:' + hashlib.sha256(canonical_json(value)).hexdigest()


def validate_r4_receipt_binding(binding):
    """Return a detached validated record from trusted local storage."""
    try:
        value = strict_json(canonical_json(binding).decode())
        if (not isinstance(value, dict) or set(value) !=
                {'schema_version', 'action', 'core_intent_hash', 'source', 'digest'} or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                value['action'] not in _ACTIONS or not isinstance(value['core_intent_hash'], str) or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', value['core_intent_hash']) or
                not isinstance(value['source'], dict) or set(value['source']) != set(_SOURCE)):
            raise ValueError('Invalid receipt binding.')
        body = {k: v for k, v in value.items() if k != 'digest'}
        if value['digest'] != _digest(body):
            raise ValueError('Invalid receipt binding digest.')
        # Reuse the wire schema for the source fields. This validation probe is
        # never published or persisted as a runtime receipt.
        decode_r4_frame(encode_r4_frame(value['source'] | dict(type='operation.receipt',
            receipt_revision=1, stage='RECEIVED_DURABLE', possible_effect=False, retry_safe=False)))
        return value
    except (CoreError, AttributeError, KeyError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_receipt_binding') from error


def project_r4_bound_receipt(binding, core_receipt, *, key, receipt_revision):
    """Project only an existing journal fact under its persisted association.

    The caller obtains the receipt with Journal.get_receipt(key). No live
    context, provider, response content or native handle is required.
    """
    value = validate_r4_receipt_binding(binding)
    source = value['source']
    if (not isinstance(key, OperationKey) or not isinstance(core_receipt, OperationReceipt) or
            type(receipt_revision) is not int or receipt_revision < 1):
        raise CoreError('VALIDATION_ERROR', 'r4_receipt_binding')
    if ((key.server_id, key.executor_id, key.operation_id) !=
            (source['server_id'], source['executor_id'], source['operation_id']) or
            core_receipt.operation_id != key.operation_id or core_receipt.session_id != source['session_id']):
        raise CoreError('SCOPE_MISMATCH', 'r4_receipt_binding', possible_effect=True)
    if core_receipt.intent_hash != value['core_intent_hash']:
        raise CoreError('OPERATION_CONFLICT', 'r4_receipt_binding', possible_effect=True)
    frame = source | dict(type='operation.receipt', receipt_revision=receipt_revision,
                          stage=core_receipt.stage, possible_effect=core_receipt.possible_effect,
                          retry_safe=core_receipt.retry_safe)
    if core_receipt.native_id is not None:
        frame['native_id'] = core_receipt.native_id
    if core_receipt.error_code is not None:
        frame['error_code'] = core_receipt.error_code
    return decode_r4_frame(encode_r4_frame(frame))
