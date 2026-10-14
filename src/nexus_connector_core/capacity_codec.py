"""Independent control extension negotiated over the authenticated NXL link.

R4 hello/welcome already permit named control capabilities. Hosts must negotiate
CAPACITY_CONTRACT_REVISION before routing these frames; the immutable R4 codec
and operation.submit bytes are not changed. A consume control binds reservations
to the hashes of subsequent ordinary canonical operations.
"""
from collections.abc import Mapping

from .capacity import (CAPACITY_CONTRACT_REVISION, CAPACITY_REASONS,
    CapacityRequest, CapacityAssessment, CapacityReservation, CapacityConsumption,
    _text, _integer, _digest)
from .models import CoreError
from .protocol import canonical_json, strict_json

MAX_CAPACITY_FRAME_BYTES = 16_384
CAPACITY_REQUEST_TYPES = frozenset({
    'capacity.assess', 'capacity.reserve', 'capacity.get', 'capacity.consume', 'capacity.release',
})
CAPACITY_FRAME_TYPES = CAPACITY_REQUEST_TYPES | {'capacity.result', 'capacity.changed', 'capacity.dispatch_state'}
_HEADER = {'contract_revision', 'type', 'server_id', 'executor_id', 'connection_id', 'connection_generation'}


def _validate(frame):
    if type(frame) is not dict:
        raise ValueError('Invalid capacity frame.')
    if frame.get('contract_revision') != CAPACITY_CONTRACT_REVISION:
        raise CoreError('VERSION_INCOMPATIBLE', 'capacity_negotiation')
    from .capacity_bundle import capacity_schema_validator
    if not capacity_schema_validator().is_valid(frame):
        raise ValueError('Invalid capacity schema.')
    kind = frame.get('type')
    if type(kind) is not str or kind not in CAPACITY_FRAME_TYPES:
        raise ValueError('Unknown capacity control.')
    for field in ('server_id', 'executor_id', 'connection_id'):
        _text(frame.get(field), field)
    _integer(frame.get('connection_generation'), 'connection_generation', minimum=1)
    expected = set(_HEADER)
    request = None
    if kind in CAPACITY_REQUEST_TYPES:
        expected |= {'request_id', 'request'}
        request = CapacityRequest.from_dict(frame.get('request'))
        if kind == 'capacity.consume':
            expected |= {'reservation_id', 'consumption'}
            binding = CapacityConsumption.from_dict(frame.get('consumption'))
            if (request.unit == 'new_session') != (binding.opening_operation_id is not None):
                raise ValueError('Consumption unit mismatch.')
        if kind == 'capacity.release':
            expected |= {'reservation_id', 'reason'}
            if frame.get('reason') not in ('LOST', 'CANCELLED', 'REVOKED', 'ROLLBACK', 'COMPLETED', 'SHUTDOWN'):
                raise ValueError('Invalid release reason.')
        if kind in ('capacity.consume', 'capacity.release'):
            _text(frame.get('reservation_id'), 'reservation_id')
    elif kind == 'capacity.result':
        expected |= {'request_id', 'request_hash', 'result_type', 'result'}
        _digest(frame.get('request_hash'), 'request_hash')
        result_type = frame.get('result_type')
        if result_type == 'reservation':
            request = CapacityReservation.from_dict(frame.get('result')).request
        elif result_type == 'assessment':
            result = CapacityAssessment.from_dict(frame.get('result'))
            if result.request_hash != frame['request_hash']:
                raise ValueError('Assessment request mismatch.')
        elif result_type != 'not_found' or frame.get('result') is not None:
            raise ValueError('Invalid capacity result.')
    elif kind == 'capacity.dispatch_state':
        expected |= {'binding_id', 'agent_id', 'session_id', 'operation_id', 'intent_hash', 'action', 'state', 'sequence'}
        for name in ('binding_id', 'agent_id', 'session_id', 'operation_id'):
            _text(frame.get(name), name)
        _digest(frame.get('intent_hash'), 'intent_hash')
        _integer(frame.get('sequence'), 'sequence', minimum=1)
        if frame.get('action') not in ('runtime.open', 'turn.submit') or frame.get('state') not in ('WAITING', 'RUNNING'):
            raise ValueError('Invalid capacity dispatch state.')
    else:
        expected |= {'binding_id', 'boot_id', 'capacity_revision', 'reason', 'valid_for_ms'}
        for field in ('binding_id', 'boot_id'):
            _text(frame.get(field), field)
        _integer(frame.get('capacity_revision'), 'capacity_revision')
        _integer(frame.get('valid_for_ms'), 'valid_for_ms', maximum=60_000)
        if type(frame.get('reason')) is not str or frame['reason'] not in CAPACITY_REASONS:
            raise ValueError('Invalid capacity observation reason.')
    if kind in CAPACITY_REQUEST_TYPES or kind == 'capacity.result':
        _text(frame.get('request_id'), 'request_id')
    if set(frame) != expected:
        raise ValueError('Unexpected or missing capacity frame fields.')
    if request is not None:
        if (request.scope.server_id, request.scope.executor_id) != (frame['server_id'], frame['executor_id']):
            raise ValueError('Capacity host scope mismatch.')
        # A query/release can reference a previous generation for reconciliation.
        # New acquisition/consumption cannot use that old generation.
        if kind in ('capacity.assess', 'capacity.reserve', 'capacity.consume'):
            if request.scope.connection_generation != frame['connection_generation']:
                raise ValueError('Stale capacity acquisition generation.')
        if kind == 'capacity.result' and request.request_hash != frame['request_hash']:
            raise ValueError('Capacity result request mismatch.')


def decode_capacity_frame(raw: bytes):
    if type(raw) is not bytes:
        raise ValueError('Capacity frames require UTF-8 bytes.')
    if len(raw) > MAX_CAPACITY_FRAME_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'capacity_decode', retry_safe=True)
    try:
        frame = strict_json(raw.decode('utf-8', errors='strict'))
        _validate(frame)
    except (UnicodeError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'capacity_decode', retry_safe=True) from error
    return frame


def encode_capacity_frame(frame: Mapping):
    if not isinstance(frame, Mapping):
        raise CoreError('VALIDATION_ERROR', 'capacity_encode', retry_safe=True)
    try:
        raw = canonical_json(dict(frame)) + b'\n'
    except (TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'capacity_encode', retry_safe=True) from error
    decode_capacity_frame(raw)
    return raw


def capacity_dispatch_state(binding, *, state, sequence):
    """Non-receipt flow control; says nothing about terminal/native effects."""
    from .receipt_binding_r4 import validate_r4_receipt_binding
    value = validate_r4_receipt_binding(binding)
    source = value['source']
    frame = {k: source[k] for k in ('server_id', 'executor_id', 'connection_id', 'connection_generation',
                                  'binding_id', 'agent_id', 'session_id', 'operation_id', 'intent_hash')}
    frame.update(contract_revision=CAPACITY_CONTRACT_REVISION, type='capacity.dispatch_state',
                 action=value['action'], state=state, sequence=sequence)
    return decode_capacity_frame(encode_capacity_frame(frame))
