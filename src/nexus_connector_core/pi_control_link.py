"""Add an exact Pi run target to a canonical R4 control on a negotiated link."""

from .frame_codec import MAX_FRAME_BYTES
from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .models import CoreError
from .native.pi_steer_facts import valid_pi_run_id, valid_pi_steer_operation
from .protocol import canonical_json, strict_json


PI_RUN_CONTROL_REVISION = 'nexus-pi-run-control-v1'
PI_RUN_CONTROL = 'pi.run.control'
_FIELDS = {'contract_revision', 'type', 'expected_pi_run_id', 'operation'}


def _validate(frame):
    if (type(frame) is not dict or frame.keys() != _FIELDS
            or frame['contract_revision'] != PI_RUN_CONTROL_REVISION or frame['type'] != PI_RUN_CONTROL
            or not valid_pi_run_id(frame['expected_pi_run_id'])):
        raise CoreError('VALIDATION_ERROR', 'pi_run_control')
    operation = decode_r4_frame(encode_r4_frame(frame['operation']))
    if (operation['type'] != 'operation.submit' or operation['action'] not in ('turn.steer', 'turn.interrupt')
            or operation.get('expected_turn_id') is not None
            or not valid_pi_steer_operation(operation['operation_id'])):
        raise CoreError('VALIDATION_ERROR', 'pi_run_control')
    return operation


def encode_pi_run_control(operation, expected_pi_run_id) -> bytes:
    frame = dict(contract_revision=PI_RUN_CONTROL_REVISION, type=PI_RUN_CONTROL,
                 expected_pi_run_id=expected_pi_run_id, operation=operation)
    frame['operation'] = _validate(frame)
    raw = canonical_json(frame) + b'\n'
    if len(raw) > MAX_FRAME_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'pi_run_control')
    return raw


def decode_pi_run_control(raw: bytes) -> dict:
    if type(raw) is not bytes:
        raise CoreError('VALIDATION_ERROR', 'pi_run_control')
    if len(raw) > MAX_FRAME_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'pi_run_control')
    try:
        frame = strict_json(raw.decode('utf-8'))
        _validate(frame)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'pi_run_control') from error
    return frame
