"""Public, passive control targeting from the Core's single adapter registry."""

from __future__ import annotations

from .models import ControlTargeting, CoreError
from .native.registry import adapter_specs


def get_control_targeting(adapter_id: str, action: str) -> ControlTargeting:
    """Describe the implemented shape independently of grants/build readiness."""
    for spec in adapter_specs():
        if spec.adapter_id == adapter_id:
            for contract in spec.control_targeting:
                if contract.action == action:
                    return contract
    raise CoreError("CAPABILITY_UNSUPPORTED", "control_target")


def validate_control_target(adapter_id: str, action: str,
                            expected_turn_id: str | None) -> ControlTargeting:
    """Refuse an unsupported shape before journal admission or native writes.

    The adapter must still recheck the actual active run/turn at the write
    frontier. A syntactically valid target is not evidence that it is current.
    """
    contract = get_control_targeting(adapter_id, action)
    if not contract.supported:
        raise CoreError("CAPABILITY_UNSUPPORTED", "control_target")
    if expected_turn_id is not None and (
            type(expected_turn_id) is not str or not 1 <= len(expected_turn_id) <= 160):
        raise CoreError("VALIDATION_ERROR", "control_target")
    if (contract.native_turn_id == "required" and expected_turn_id is None or
            contract.native_turn_id == "forbidden" and expected_turn_id is not None):
        raise CoreError("CAPABILITY_UNSUPPORTED", "control_target")
    return contract
