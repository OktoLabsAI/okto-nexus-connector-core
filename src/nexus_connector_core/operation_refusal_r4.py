"""Durable pre-admission refusal under an authenticated host's lease denial.

No execution context or authority is invented. A domain-separated journal
identity fences the original operation ID, including for older Core consumers
which would calculate a different native intent hash. Hosts must persist this
non-secret association before calling persist_r4_lease_refusal, so a crash
between admission and the terminal receipt can finish the same refusal.
"""
from hashlib import sha256

from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .lease_denial import decode_lease_denial, encode_lease_denial
from .models import CoreError, OperationKey, OperationReceipt
from .ports import Journal
from .protocol import canonical_json, strict_json
from .receipt_binding_r4 import validate_r4_receipt_binding

_SOURCE = ('protocol_major', 'contract_revision', 'server_id', 'executor_id',
           'binding_id', 'agent_id', 'session_id', 'connection_id',
           'connection_generation', 'operation_id', 'intent_hash')
_SCOPE = ('server_id', 'executor_id', 'binding_id', 'agent_id', 'workspace_id',
          'workspace_binding_id', 'session_id', 'session_owner_generation',
          'authorization_revision', 'configuration_revision', 'binding_revision', 'credential_epoch')
_ACTIONS = {'runtime.open', 'turn.submit', 'turn.steer', 'approval.decide', 'input.provide'}


def _digest(value):
    return 'sha256:' + sha256(canonical_json(value)).hexdigest()


def _binding(source, scope, action, denial, grant_id):
    body = dict(schema_version=1, source=source, action=action,
        core_intent_hash=_digest(dict(domain='nexus-r4-lease-refusal-v1',
            source=source, scope=scope, action=action, denial=denial, grant_id=grant_id)))
    return validate_r4_receipt_binding(dict(body, digest=_digest(body)))


def prepare_r4_lease_refusal(submit, denial):
    """Only the host that correlated the authenticated denial may call this."""
    frame = decode_r4_frame(encode_r4_frame(submit))
    denial = decode_lease_denial(encode_lease_denial(denial))
    if frame['type'] != 'operation.submit' or frame['action'] not in _ACTIONS:
        raise CoreError('VALIDATION_ERROR', 'r4_operation_refusal')
    if (frame['action'] in ('approval.decide', 'input.provide')
            and frame['payload'].get('decision') in ('decline', 'cancel')
            and all(frame['payload'].get(k) is None for k in ('response','response_ref','response_digest'))):
        raise CoreError('VALIDATION_ERROR', 'r4_operation_refusal')
    scope, source = {k: frame[k] for k in _SCOPE}, {k: frame[k] for k in _SOURCE}
    request = denial['request']
    if request['purpose'] == 'initial' and (frame['action'] != 'runtime.open' or frame['grant_id'] != request['grant_id']):
        raise CoreError('SCOPE_MISMATCH', 'r4_operation_refusal')
    return validate_r4_lease_refusal(dict(schema_version=1, scope=scope, denial=denial, grant_id=frame['grant_id'],
        binding=_binding(source, scope, frame['action'], denial, frame['grant_id'])))


def validate_r4_lease_refusal(value):
    """Validate a detached persisted association; never a native command."""
    try:
        value = strict_json(canonical_json(value).decode())
        if (type(value) is not dict or set(value) != {'schema_version','scope','denial','binding','grant_id'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1):
            raise ValueError('Invalid refusal association.')
        denial = decode_lease_denial(encode_lease_denial(value['denial']))
        binding = validate_r4_receipt_binding(value['binding'])
        source, request, scope = binding['source'], denial['request'], value['scope']
        if (type(value['grant_id']) is not str or not 1 <= len(value['grant_id']) <= 160
                or binding['action'] not in _ACTIONS or scope != request['scope'] or set(scope) != set(_SCOPE)
                or any(source[k] != request[k] for k in ('connection_id','connection_generation'))
                or any(source[k] != scope[k] for k in ('server_id','executor_id','binding_id','agent_id','session_id'))
                or request['purpose'] == 'initial' and (binding['action'] != 'runtime.open' or value['grant_id'] != request['grant_id'])
                or binding != _binding(source, scope, binding['action'], denial, value['grant_id'])):
            raise CoreError('SCOPE_MISMATCH', 'r4_operation_refusal')
        return value
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_operation_refusal') from error


async def persist_r4_lease_refusal(journal: Journal, refusal):
    """Fence an absent native operation, or finish the same persisted refusal.

    A different existing journal intent (including uncertain native effects)
    is a conflict and remains untouched. Uses normal admission quota, never
    the space reserved for interrupt/close. There is no session claim or slot.
    """
    value = validate_r4_lease_refusal(refusal)
    return await _persist_refusal(journal, value['binding'], value['denial']['code'])


async def _persist_refusal(journal, binding, code):
    """One journal CAS for both authenticated denial and host-side fencing."""
    source = binding['source']
    key = OperationKey(source['server_id'], source['executor_id'], source['operation_id'])
    old, _ = await journal.admit(key, binding['core_intent_hash'], source['session_id'])
    receipt = OperationReceipt(source['operation_id'], binding['core_intent_hash'], 'FAILED',
        False, True, source['session_id'], error_code=code)
    if old == receipt:
        return old
    if old.stage != 'RECEIVED_DURABLE' or old.possible_effect or old.native_id is not None:
        raise CoreError('OPERATION_CONFLICT', 'r4_operation_refusal', possible_effect=True,
                        operation_id=key.operation_id)
    return await journal.record_receipt(key, receipt)


def prepare_r4_stopped_refusal(submit, *, scope, connection_id, connection_generation, error_code):
    """Refuse unadmitted productive work after its trusted host latched a fence.

    This is a local association, not a fabricated lease denial or proof of
    process termination. The host must retain containment separately. A
    different existing journal intent always wins over this refusal.
    """
    frame = decode_r4_frame(encode_r4_frame(submit))
    if frame['type'] != 'operation.submit' or frame['action'] not in _ACTIONS:
        raise CoreError('VALIDATION_ERROR', 'r4_stopped_refusal')
    if (frame['action'] in ('approval.decide', 'input.provide')
            and frame['payload'].get('decision') in ('decline', 'cancel')
            and all(frame['payload'].get(k) is None for k in ('response', 'response_ref', 'response_digest'))):
        raise CoreError('VALIDATION_ERROR', 'r4_stopped_refusal')
    if (scope != {k: frame[k] for k in _SCOPE} or connection_id != frame['connection_id']
            or type(connection_generation) is not int or connection_generation != frame['connection_generation']):
        raise CoreError('SCOPE_MISMATCH', 'r4_stopped_refusal')
    value = dict(schema_version=1, kind='stopped_session', scope=scope,
        error_code=error_code, grant_id=frame['grant_id'])
    value['binding'] = _stopped_binding(value, {k: frame[k] for k in _SOURCE}, frame['action'])
    return validate_r4_stopped_refusal(value)


def _stopped_binding(value, source, action):
    body = dict(schema_version=1, source=source, action=action,
        core_intent_hash=_digest(dict(domain='nexus-r4-stopped-refusal-v1', source=source,
            scope=value['scope'], action=action, error_code=value['error_code'], grant_id=value['grant_id'])))
    return validate_r4_receipt_binding(dict(body, digest=_digest(body)))


def validate_r4_stopped_refusal(value):
    from .native_action_bridge import native_action_scope
    try:
        value = strict_json(canonical_json(value).decode())
        if (type(value) is not dict or set(value) != {'schema_version', 'kind', 'scope', 'error_code', 'grant_id', 'binding'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['kind'] != 'stopped_session'
                or value['error_code'] not in ('LEASE_EXPIRED', 'LEASE_REVALIDATION_REQUIRED')
                or type(value['grant_id']) is not str or not 1 <= len(value['grant_id']) <= 160):
            raise ValueError('Invalid stopped-session refusal association.')
        scope = native_action_scope(value['scope'])
        binding = validate_r4_receipt_binding(value['binding'])
        source = binding['source']
        if (binding['action'] not in _ACTIONS
                or any(source[k] != scope[k] for k in ('server_id','executor_id','binding_id','agent_id','session_id'))
                or binding != _stopped_binding(value, source, binding['action'])):
            raise CoreError('SCOPE_MISMATCH', 'r4_stopped_refusal')
        return value
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_stopped_refusal') from error


def validate_r4_operation_refusal(value):
    """Validate either supported local refusal association, without fallback."""
    if isinstance(value, dict) and value.get('kind') == 'stopped_session':
        return validate_r4_stopped_refusal(value)
    return validate_r4_lease_refusal(value)


async def persist_r4_operation_refusal(journal: Journal, refusal):
    value = validate_r4_operation_refusal(refusal)
    code = value['error_code'] if value.get('kind') == 'stopped_session' else value['denial']['code']
    return await _persist_refusal(journal, value['binding'], code)
