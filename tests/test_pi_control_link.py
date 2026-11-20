import pytest

from nexus_connector_core import CoreError, decode_control_frame, r4_submit_intent_hash
from nexus_connector_core.pi_control_link import PI_RUN_CONTROL_REVISION, encode_pi_run_control
from nexus_connector_core.protocol import canonical_json
from nexus_connector_core.targeted_control_link import CLAUDE_OPERATION_INTERRUPT_CODEC, CLAUDE_OPERATION_STEER_CODEC
from test_r4_receipt_bridge import _frame


RUN = 'prun_' + 'a' * 32


def operation(action, payload, *, expected_turn_id=None):
    frame = _frame() | dict(action=action, payload=payload, expected_turn_id=expected_turn_id)
    return frame | {'intent_hash': r4_submit_intent_hash(frame)}


@pytest.mark.parametrize('action,payload', [
    ('turn.steer', {'text': 'Review this boundary'}),
    ('turn.interrupt', {'reason': 'Stop this run'}),
])
def test_exact_pi_control_requires_negotiation_and_preserves_canonical_identity(action, payload):
    source = operation(action, payload)
    raw = encode_pi_run_control(source, RUN)
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_control_frame(raw)
    outer = decode_control_frame(raw, capabilities=(PI_RUN_CONTROL_REVISION,))
    assert outer['operation'] == source and outer['expected_pi_run_id'] == RUN
    for changed in (outer | {'expected_pi_run_id': 'missing'},
                    outer | {'extra': True},
                    outer | {'operation': source | {'intent_hash': 'sha256:' + '0' * 64}}):
        with pytest.raises(CoreError, match='VALIDATION_ERROR'):
            decode_control_frame(canonical_json(changed), capabilities=(PI_RUN_CONTROL_REVISION,))


@pytest.mark.parametrize('source', [
    operation('turn.submit', {'text': 'A new turn'}),
    operation('turn.interrupt', {'reason': 'Stop'}, expected_turn_id='native-turn'),
])
def test_pi_control_cannot_wrap_a_new_turn_or_combine_two_targets(source):
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        encode_pi_run_control(source, RUN)


@pytest.mark.parametrize('codec,other,action,payload', [
    (CLAUDE_OPERATION_STEER_CODEC, CLAUDE_OPERATION_INTERRUPT_CODEC,
     'turn.steer', {'text': 'Replace the reviewed turn'}),
    (CLAUDE_OPERATION_INTERRUPT_CODEC, CLAUDE_OPERATION_STEER_CODEC,
     'turn.interrupt', {'reason': 'Interrupt the reviewed turn'}),
])
def test_claude_control_carries_a_distinct_operation_and_requires_its_revision(codec, other, action, payload):
    source = operation(action, payload)
    raw = codec.encode(source, 'active-operation')
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_control_frame(raw, capabilities=(PI_RUN_CONTROL_REVISION, other.revision))
    decoded = decode_control_frame(raw, capabilities=(codec.revision,))
    assert decoded['expected_claude_operation_id'] == 'active-operation' and decoded['operation'] == source
    for invalid in (source['operation_id'], '', 'core.internal.absent', 'bad\nref', 'x' * 161):
        with pytest.raises(CoreError, match='VALIDATION_ERROR'):
            codec.encode(source, invalid)
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        other.encode(source, 'active-operation')
