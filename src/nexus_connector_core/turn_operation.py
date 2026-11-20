"""Keep explicit literal intent in both the Core and R4 turn identities."""

from .frame_codec_r4 import decode_r4_frame
from .models import CoreError, Operation, TurnOperation
from .protocol import canonical_json


PI_LITERAL_INPUT_REVISION = "nexus-pi-literal-input-v1"


def turn_operation_semantic(operation: TurnOperation) -> Operation:
    if (not isinstance(operation, TurnOperation) or type(operation.literal) is not bool
            or not isinstance(operation.text, str) or not operation.text
            or len(operation.text.encode("utf-8")) > 1024 * 1024
            or (operation.literal and operation.expected_turn_id is not None)):
        raise CoreError("VALIDATION_ERROR", "submit")
    payload = {"text": operation.text}
    if operation.literal:
        payload["literal"] = True
    return Operation(operation.operation_id, operation.session_id, "turn.submit",
                     payload, operation.expected_turn_id)


def r4_turn_operation(frame) -> TurnOperation:
    """Translate an exact R4 submit, leaving delivery metadata on the wire."""
    parsed = decode_r4_frame(canonical_json(dict(frame)))
    if parsed["type"] != "operation.submit" or parsed["action"] != "turn.submit":
        raise CoreError("VALIDATION_ERROR", "r4_turn")
    payload = parsed["payload"]
    return TurnOperation(parsed["operation_id"], parsed["session_id"], payload["text"],
                         parsed.get("expected_turn_id"), literal=payload.get("literal", False))
