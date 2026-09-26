from copy import deepcopy

import pytest

from nexus_connector_core import CoreError, OperationReceipt
from nexus_connector_core.frame_codec import decode_frame, encode_frame
from nexus_connector_core.receipt_reducer import receipt_frame, reduce_receipt


_HASH = "sha256:" + "a" * 64


def _frame(stage, *, possible_effect=True, retry_safe=False):
    return receipt_frame(OperationReceipt(
        "op", _HASH, stage, possible_effect, retry_safe, "session"),
        server_id="server", executor_id="executor")


def test_producer_emits_bundled_schema_frame_without_optional_nulls():
    frame = _frame("SUBMITTED")
    assert frame["type"] == "operation.receipt"
    assert "native_id" not in frame and "error_code" not in frame
    assert decode_frame(encode_frame(frame).rstrip(b"\n")) == frame


def test_terminal_without_intermediate_ack_records_only_observed_stages():
    durable = reduce_receipt(None, _frame("RECEIVED_DURABLE", possible_effect=False))
    final = reduce_receipt(durable, _frame("SUCCEEDED"))
    assert final.receipt.stage == "SUCCEEDED"
    assert tuple(item.stage for item in final.observed) == (
        "RECEIVED_DURABLE", "SUCCEEDED")
    assert reduce_receipt(final, _frame("SUBMITTED")) is final
    assert reduce_receipt(final, _frame("SUCCEEDED")) is final


def test_unknown_is_not_safe_retry_and_later_evidence_resolves_it():
    started = reduce_receipt(None, _frame("SUBMISSION_STARTED"))
    unknown = reduce_receipt(started, _frame("OUTCOME_UNKNOWN"))
    assert unknown.receipt.possible_effect and not unknown.receipt.retry_safe
    assert reduce_receipt(unknown, _frame("PREPARED")) is unknown
    running = reduce_receipt(unknown, _frame("RUNNING"))
    assert running.receipt.stage == "RUNNING"
    assert tuple(item.stage for item in running.observed) == (
        "SUBMISSION_STARTED", "OUTCOME_UNKNOWN", "RUNNING")


def test_out_of_order_progress_does_not_regress_or_fabricate_stages():
    current = reduce_receipt(None, _frame("RUNNING"))
    assert reduce_receipt(current, _frame("ACCEPTED")) is current
    waiting = reduce_receipt(current, _frame("WAITING_INPUT"))
    assert waiting.receipt.stage == "WAITING_INPUT"
    assert reduce_receipt(waiting, _frame("RUNNING")) is waiting


def test_conflicting_identity_stage_or_terminal_fails_closed():
    current = reduce_receipt(None, _frame("SUBMITTED"))
    wrong = deepcopy(_frame("RUNNING"))
    wrong["intent_hash"] = "sha256:" + "b" * 64
    with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
        reduce_receipt(current, wrong)
    changed = deepcopy(_frame("SUBMITTED"))
    changed["native_id"] = "late-native-id"
    with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
        reduce_receipt(current, changed)
    final = reduce_receipt(current, _frame("SUCCEEDED"))
    with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
        reduce_receipt(final, _frame("FAILED"))


def test_invalid_or_wrong_family_frame_is_rejected_before_reduce():
    invalid = deepcopy(_frame("SUBMITTED"))
    invalid["unknown_field"] = True
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        reduce_receipt(None, invalid)
    wrong = deepcopy(_frame("SUBMITTED"))
    wrong["contract_revision"] = "nxl-1-agent-centric-http-only-2026-09-25-r1"
    with pytest.raises(CoreError):
        reduce_receipt(None, wrong)
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        reduce_receipt(None, {"type": "heartbeat"})


def test_invalid_unknown_receipt_cannot_be_produced():
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        _frame("OUTCOME_UNKNOWN", possible_effect=False, retry_safe=True)
