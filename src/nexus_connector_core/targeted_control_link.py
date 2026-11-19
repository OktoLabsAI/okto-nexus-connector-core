"""Strict negotiated envelopes for existing R4 controls with exact targets."""

from collections.abc import Callable
from dataclasses import dataclass

from .frame_codec import MAX_FRAME_BYTES
from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .identifiers import validate_external_id
from .models import CoreError
from .native.pi_steer_facts import valid_pi_run_id, valid_pi_steer_operation
from .protocol import canonical_json, strict_json


@dataclass(frozen=True, slots=True)
class TargetedControlCodec:
    revision: str
    kind: str
    target_field: str
    actions: tuple[str, ...]
    valid_target: Callable[[object, str], bool]
    stage: str

    def _validate(self, frame):
        if (type(frame) is not dict or frame.keys() != {'contract_revision', 'type', self.target_field, 'operation'}
                or frame['contract_revision'] != self.revision or frame['type'] != self.kind):
            raise CoreError('VALIDATION_ERROR', self.stage)
        operation = decode_r4_frame(encode_r4_frame(frame['operation']))
        if (operation['type'] != 'operation.submit' or operation['action'] not in self.actions
                or operation.get('expected_turn_id') is not None
                or not valid_pi_steer_operation(operation['operation_id'])
                or not self.valid_target(frame[self.target_field], operation['operation_id'])):
            raise CoreError('VALIDATION_ERROR', self.stage)
        return operation

    def encode(self, operation, target) -> bytes:
        frame = {'contract_revision': self.revision, 'type': self.kind, self.target_field: target, 'operation': operation}
        frame['operation'] = self._validate(frame)
        raw = canonical_json(frame) + b'\n'
        if len(raw) > MAX_FRAME_BYTES:
            raise CoreError('CAPACITY_EXCEEDED', self.stage)
        return raw

    def decode(self, raw: bytes) -> dict:
        if type(raw) is not bytes:
            raise CoreError('VALIDATION_ERROR', self.stage)
        if len(raw) > MAX_FRAME_BYTES:
            raise CoreError('CAPACITY_EXCEEDED', self.stage)
        try:
            frame = strict_json(raw.decode('utf-8'))
            self._validate(frame)
        except (UnicodeError, ValueError, RecursionError) as error:
            raise CoreError('VALIDATION_ERROR', self.stage) from error
        return frame


def _valid_claude_target(target, operation_id):
    try:
        return (validate_external_id(target, stage='claude_operation_steer') != operation_id
                and target.isprintable())
    except CoreError:
        return False


PI_RUN_CONTROL_CODEC = TargetedControlCodec(
    'nexus-pi-run-control-v1', 'pi.run.control', 'expected_pi_run_id',
    ('turn.steer', 'turn.interrupt'), lambda target, _: valid_pi_run_id(target), 'pi_run_control')
CLAUDE_OPERATION_STEER_CODEC = TargetedControlCodec(
    'nexus-claude-operation-steer-v1', 'claude.operation.steer', 'expected_claude_operation_id',
    ('turn.steer',), _valid_claude_target, 'claude_operation_steer')

TARGETED_CONTROL_CODECS = (PI_RUN_CONTROL_CODEC, CLAUDE_OPERATION_STEER_CODEC)
