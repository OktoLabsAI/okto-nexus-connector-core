"""Negotiated, connection-bound report for an effect-free prelease opening.

This codec verifies the report's internal provenance. Only the Server's live
authenticated control channel may authorize it; a receipt ticket alone does
not prove that the original opening producer was stopped.
"""
from __future__ import annotations

from .capacity import CapacityReservation
from .frame_codec_r4 import decode_r4_frame
from .models import CoreError, OperationKey, OperationReceipt
from .protocol import canonical_json, strict_json
from .receipt_binding_r4 import project_r4_bound_receipt
from .startup_refusal_r4 import validate_r4_startup_refusal


STARTUP_REFUSAL_REVISION = 'nexus-startup-refusal-v1'
MAX_STARTUP_REFUSAL_BYTES = 32768
_SCOPE = ('server_id', 'executor_id', 'agent_id', 'binding_id', 'workspace_id',
          'workspace_binding_id', 'session_id', 'session_owner_generation', 'authorization_revision',
          'configuration_revision', 'binding_revision', 'credential_epoch')


def _request(value):
    if (set(value) != {'contract_revision', 'type', 'request_id', 'refusal',
                       'receipt', 'capacity', 'native_absent'}
            or value['type'] != 'startup.refuse' or value['native_absent'] is not True):
        raise ValueError('Invalid startup refusal request.')
    request_id = value['request_id']
    if type(request_id) is not str or not 1 <= len(request_id) <= 160 or any(ord(c) < 33 for c in request_id):
        raise ValueError('Invalid startup refusal request ID.')
    refusal = validate_r4_startup_refusal(value['refusal'])
    source = refusal['binding']['source']
    receipt = decode_r4_frame(canonical_json(value['receipt']))
    expected = project_r4_bound_receipt(refusal['binding'], OperationReceipt(
        source['operation_id'], refusal['binding']['core_intent_hash'], 'FAILED',
        False, True, source['session_id'], error_code='PREPARATION_FAILED'),
        key=OperationKey(source['server_id'], source['executor_id'], source['operation_id']),
        receipt_revision=1)
    if receipt != expected:
        raise CoreError('SCOPE_MISMATCH', 'startup_refusal_report')
    if value['capacity'] is not None:
        reservation = CapacityReservation.from_dict(value['capacity'])
        capacity = reservation.request
        consumption = reservation.consumption
        if (reservation.state != 'RELEASED' or capacity.unit != 'new_session'
                or consumption is None or consumption.opening_operation_id != source['operation_id']
                or consumption.opening_intent_hash != source['intent_hash']
                or capacity.scope.connection_generation != source['connection_generation']
                or any(getattr(capacity.scope, name) != refusal['scope'][name] for name in _SCOPE)):
            raise CoreError('SCOPE_MISMATCH', 'startup_refusal_capacity')
    return value


def decode_startup_refusal(raw):
    if type(raw) is not bytes:
        raise ValueError('Startup refusal frames require UTF-8 bytes.')
    if len(raw) > MAX_STARTUP_REFUSAL_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'startup_refusal_decode')
    try:
        value = strict_json(raw.decode('utf-8', errors='strict'))
        canonical_json(value)
        if type(value) is not dict or value.get('contract_revision') != STARTUP_REFUSAL_REVISION:
            raise ValueError('Unsupported startup refusal revision.')
        if value.get('type') == 'startup.refuse':
            return _request(value)
        if (set(value) != {'contract_revision', 'type', 'request'}
                or value['type'] not in ('startup.refuse.accepted', 'startup.refuse.deferred')):
            raise ValueError('Invalid startup refusal reply.')
        _request(value['request'])
        return value
    except CoreError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, AttributeError) as error:
        raise CoreError('VALIDATION_ERROR', 'startup_refusal_decode') from error


def encode_startup_refusal(frame):
    try:
        raw = canonical_json(frame)
    except (TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'startup_refusal_encode') from error
    if len(raw) + 1 > MAX_STARTUP_REFUSAL_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'startup_refusal_encode')
    decode_startup_refusal(raw)
    return raw + b'\n'


def startup_refusal_accepted(request):
    original = decode_startup_refusal(encode_startup_refusal(request))
    if original['type'] != 'startup.refuse':
        raise CoreError('VALIDATION_ERROR', 'startup_refusal_ack')
    return dict(contract_revision=STARTUP_REFUSAL_REVISION,
                type='startup.refuse.accepted', request=original)


def startup_refusal_deferred(request):
    original = startup_refusal_accepted(request)['request']
    return dict(contract_revision=STARTUP_REFUSAL_REVISION,
                type='startup.refuse.deferred', request=original)
