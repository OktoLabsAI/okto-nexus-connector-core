"""R4 control and lane ACKs cannot imply a productive session."""

from __future__ import annotations

from dataclasses import replace

import pytest

from nexus_connector_core import (
    CoreError, R4_PREVIEW_REVISION, R4AttachAttempt, R4ReconcileAttempt,
    reduce_r4_binding_attached, reduce_r4_reconcile_accepted, r4_lane_ready,
)


def _base(kind: str) -> dict:
    return {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
            "type": kind}


def test_control_ack_and_lane_ack_need_matching_attempts_and_current_ttl():
    reconcile = R4ReconcileAttempt(
        "reconcile", "srv", "exe", "connection", 2, "boot")
    reconcile_ack = {**_base("reconcile.accepted"),
                     "reconcile_id": "reconcile", "server_id": "srv",
                     "executor_id": "exe", "connection_id": "connection",
                     "connection_generation": 2,
                     "recovery_remaining": False,
                     "ready_lane_ids": ["binding"],
                     "session_lease_requirements": ["session"]}
    control = reduce_r4_reconcile_accepted(reconcile, reconcile_ack)
    assert control.ready and control.session_lease_requirements == ("session",)
    attach = R4AttachAttempt(
        "attach", "srv", "exe", "binding", "agent", 1, 1, 1,
        "connection", 2, "boot", 10.0)
    attach_ack = {**_base("binding.attached"),
                  "attach_request_id": "attach", "server_id": "srv",
                  "executor_id": "exe", "binding_id": "binding",
                  "agent_id": "agent", "credential_epoch": 1,
                  "authorization_revision": 1,
                  "configuration_revision": 1,
                  "connection_id": "connection",
                  "connection_generation": 2, "expires_in": 60}
    lane = reduce_r4_binding_attached(
        attach, attach_ack, received_at_monotonic=11.0)
    assert lane.deadline_monotonic == 70.0
    assert r4_lane_ready(control, lane, boot_id="boot", now_monotonic=12.0)
    assert not r4_lane_ready(control, lane, boot_id="boot", now_monotonic=70.0)
    assert not r4_lane_ready(control, lane, boot_id="new-boot", now_monotonic=12.0)
    assert not r4_lane_ready(replace(control, recovery_remaining=True), lane,
                             boot_id="boot", now_monotonic=12.0)
    assert not r4_lane_ready(replace(control, ready_lane_ids=()), lane,
                             boot_id="boot", now_monotonic=12.0)
    assert not r4_lane_ready(replace(control, connection_generation=3), lane,
                             boot_id="boot", now_monotonic=12.0)
    with pytest.raises(CoreError):
        reduce_r4_binding_attached(
            attach, {**attach_ack, "credential_epoch": 2},
            received_at_monotonic=11.0)
    with pytest.raises(CoreError):
        reduce_r4_binding_attached(
            attach, attach_ack, received_at_monotonic=70.0)
    with pytest.raises(CoreError):
        reduce_r4_reconcile_accepted(
            reconcile, {**reconcile_ack, "connection_generation": 3})
