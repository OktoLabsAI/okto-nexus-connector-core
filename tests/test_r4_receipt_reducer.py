"""R4 receipt revisions cannot create or relabel an operation."""

from __future__ import annotations

import pytest

from nexus_connector_core import (
    CoreError, R4_PREVIEW_REVISION, reduce_r4_receipt,
)


def _frame(**changes) -> dict:
    frame = {
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "operation.receipt", "server_id": "srv",
        "executor_id": "exe", "binding_id": "binding",
        "agent_id": "agent", "session_id": "session",
        "connection_id": "connection", "connection_generation": 1,
        "operation_id": "op", "intent_hash": "sha256:" + "a" * 64,
        "receipt_revision": 1, "stage": "RECEIVED_DURABLE",
        "possible_effect": False, "retry_safe": True,
    }
    frame.update(changes)
    return frame


def test_r4_receipt_replay_order_and_source_scope():
    with pytest.raises(CoreError):
        reduce_r4_receipt(None, _frame(receipt_revision=2))
    first = reduce_r4_receipt(None, _frame())
    assert reduce_r4_receipt(first, _frame()) is first
    with pytest.raises(CoreError):
        reduce_r4_receipt(first, _frame(connection_id="different"))
    with pytest.raises(CoreError):
        reduce_r4_receipt(first, _frame(agent_id="foreign", receipt_revision=2))
    with pytest.raises(CoreError):
        reduce_r4_receipt(first, _frame(connection_generation=2,
                                        receipt_revision=2))
    with pytest.raises(CoreError):
        reduce_r4_receipt(first, _frame(receipt_revision=3, stage="RUNNING",
                                        possible_effect=True,
                                        retry_safe=False))
    running = reduce_r4_receipt(
        first, _frame(receipt_revision=2, stage="RUNNING",
                      possible_effect=True, retry_safe=False,
                      native_id="native-turn"),
    )
    assert running.possible_effect and running.native_id == "native-turn"
    with pytest.raises(CoreError):
        reduce_r4_receipt(
            running, _frame(receipt_revision=3, stage="FAILED",
                            possible_effect=False, retry_safe=True),
        )
    with pytest.raises(CoreError):
        reduce_r4_receipt(
            running, _frame(receipt_revision=3, stage="SUCCEEDED",
                            possible_effect=True, retry_safe=True),
        )
    succeeded = reduce_r4_receipt(
        running, _frame(receipt_revision=3, stage="SUCCEEDED",
                        possible_effect=True, retry_safe=False,
                        native_id="native-turn"),
    )
    assert succeeded.stage == "SUCCEEDED"
    with pytest.raises(CoreError):
        reduce_r4_receipt(
            succeeded, _frame(receipt_revision=4, stage="FAILED",
                              possible_effect=True, retry_safe=False),
        )
