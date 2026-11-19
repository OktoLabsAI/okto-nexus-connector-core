"""Add an exact Pi run target to a canonical R4 control on a negotiated link."""

from .targeted_control_link import PI_RUN_CONTROL_CODEC


PI_RUN_CONTROL_REVISION = PI_RUN_CONTROL_CODEC.revision
PI_RUN_CONTROL = PI_RUN_CONTROL_CODEC.kind


def encode_pi_run_control(operation, expected_pi_run_id) -> bytes:
    return PI_RUN_CONTROL_CODEC.encode(operation, expected_pi_run_id)


def decode_pi_run_control(raw: bytes) -> dict:
    return PI_RUN_CONTROL_CODEC.decode(raw)
