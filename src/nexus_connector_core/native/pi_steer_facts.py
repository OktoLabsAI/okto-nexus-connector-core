"""Bounded facts from the reviewed hosted Pi RPC owner."""

import re


PI_STEER_EVENT = "nexus_pi_steer"
_RUN_ID = re.compile(r"prun_[a-f0-9]{32}\Z", re.ASCII)
_CONTROL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z", re.ASCII)


def valid_pi_run_id(value) -> bool:
    return isinstance(value, str) and _RUN_ID.fullmatch(value) is not None


def valid_pi_steer_operation(value) -> bool:
    return isinstance(value, str) and _CONTROL_ID.fullmatch(value) is not None


def valid_pi_steer_fact(payload) -> bool:
    return (payload.keys() == {"type", "run_id", "operation_id", "stage"}
            and payload["type"] == PI_STEER_EVENT
            and valid_pi_run_id(payload["run_id"]) and valid_pi_steer_operation(payload["operation_id"])
            and payload["stage"] in ("queued", "consumed", "discarded"))
