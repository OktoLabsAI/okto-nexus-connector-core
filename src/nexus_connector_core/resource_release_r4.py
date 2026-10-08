"""Correlate historical release with the original effect-capable opening.

The digest is an integrity/correlation marker for an authenticated report.
It is not a signature, live ownership proof, takeover permission or a receipt
for a close operation that never occurred.
"""
import hashlib
import re

from .models import ClaimedSession, CoreError, OperationKey, OwnedSlotState
from .protocol import canonical_json
from .receipt_binding_r4 import project_r4_bound_receipt, validate_r4_receipt_binding


def r4_resource_release_digest(*, server_id, executor_id, session_id,
                               opening_operation_id, opening_intent_hash,
                               owner_generation):
    values = (server_id, executor_id, session_id, opening_operation_id)
    if (any(type(v) is not str or not 1 <= len(v) <= 160 for v in values)
            or type(owner_generation) is not int or not 1 <= owner_generation <= 9007199254740991
            or type(opening_intent_hash) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", opening_intent_hash) is None):
        raise CoreError("VALIDATION_ERROR", "r4_resource_release")
    body = dict(kind="core-resource-release-v1", server_id=server_id, executor_id=executor_id,
                session_id=session_id, opening_operation_id=opening_operation_id,
                opening_intent_hash=opening_intent_hash, owner_generation=owner_generation,
                released=True)
    return "sha256:" + hashlib.sha256(canonical_json(body)).hexdigest()


def project_r4_resource_release(binding, claim, slot, receipt):
    binding = validate_r4_receipt_binding(binding)
    if (not isinstance(claim, ClaimedSession) or not isinstance(slot, OwnedSlotState)
            or slot.released is not True or slot.key != claim.key
            or slot.opening_operation_id != claim.opening_operation_id
            or binding["action"] != "runtime.open"):
        raise CoreError("SCOPE_MISMATCH", "r4_resource_release")
    key = OperationKey(claim.key.server_id, claim.key.executor_id, claim.opening_operation_id)
    projected = project_r4_bound_receipt(binding, receipt, key=key, receipt_revision=1)
    # The native tree can exist before the successful opening receipt commits.
    # The released owned slot is the stop proof; an uncertain opening receipt
    # preserves that uncertainty rather than making containment unrecoverable.
    if (projected["session_id"] != claim.key.session_id
            or projected["stage"] not in ("SUBMISSION_STARTED", "SUBMITTED", "RUNNING", "OUTCOME_UNKNOWN", "SUCCEEDED")
            or not projected['possible_effect']):
        raise CoreError("RECONCILIATION_REQUIRED", "r4_resource_release")
    digest = r4_resource_release_digest(server_id=key.server_id, executor_id=key.executor_id,
        session_id=claim.key.session_id, opening_operation_id=key.operation_id,
        opening_intent_hash=projected["intent_hash"], owner_generation=claim.opening_owner_generation)
    return dict(session_id=claim.key.session_id, owner_generation=claim.opening_owner_generation,
                process_state="EXITED", proof_digest=digest)
