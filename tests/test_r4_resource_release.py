from dataclasses import replace
import hashlib

import pytest
from nexus_connector_core import (
    ClaimedSession, CoreError, OperationReceipt, OwnedSlotState, SessionKey,
    project_r4_resource_release, r4_resource_release_digest,
)
from nexus_connector_core.protocol import canonical_json
from test_r4_receipt_bridge import _frame


@pytest.fixture
def release():
    frame = _frame()
    source = {k:frame[k] for k in (
        "protocol_major","contract_revision","server_id","executor_id","binding_id","agent_id",
        "session_id","connection_id","connection_generation","operation_id","intent_hash")}
    body = dict(schema_version=1, action="runtime.open", core_intent_hash="sha256:"+"a"*64, source=source)
    binding = body | dict(digest="sha256:"+hashlib.sha256(canonical_json(body)).hexdigest())
    key = SessionKey(frame["server_id"],frame["executor_id"],frame["session_id"])
    claim = ClaimedSession(key,frame["operation_id"],1,1)
    slot = OwnedSlotState(key,claim.opening_operation_id,True)
    receipt = OperationReceipt(claim.opening_operation_id,body["core_intent_hash"],
                               "SUBMITTED",True,False,key.session_id)
    return binding,claim,slot,receipt


def test_release_projection_correlates_opening_without_creating_close_receipt(release):
    binding,claim,slot,receipt = release
    fact = project_r4_resource_release(*release)
    assert fact == dict(session_id=claim.key.session_id,owner_generation=1,process_state="EXITED",
        proof_digest=r4_resource_release_digest(server_id=claim.key.server_id,
            executor_id=claim.key.executor_id,session_id=claim.key.session_id,
            opening_operation_id=claim.opening_operation_id,
            opening_intent_hash=binding["source"]["intent_hash"],owner_generation=1))
    assert receipt.stage == "SUBMITTED"


@pytest.mark.parametrize("fault", ["missing","active","server","executor","session","operation",
                                    "receipt_hash","receipt_session","receipt_stage","generation","action"])
def test_unrelated_or_unproven_release_is_refused(release,fault):
    binding,claim,slot,receipt = release
    if fault == "missing": slot = None
    elif fault == "active": slot = replace(slot,released=False)
    elif fault in ("server","executor","session"):
        field={"server":"server_id","executor":"executor_id","session":"session_id"}[fault]
        slot = replace(slot,key=replace(slot.key,**{field:"foreign"}))
    elif fault == "operation": slot = replace(slot,opening_operation_id="foreign")
    elif fault == "receipt_hash": receipt = replace(receipt,intent_hash="sha256:"+"f"*64)
    elif fault == "receipt_session": receipt = replace(receipt,session_id="foreign")
    elif fault == "receipt_stage": receipt = replace(receipt,stage="OUTCOME_UNKNOWN")
    elif fault == "generation": claim = replace(claim,opening_owner_generation=None)
    elif fault == "action":
        body={k:v for k,v in binding.items() if k!="digest"} | dict(action="turn.submit")
        binding=body | dict(digest="sha256:"+hashlib.sha256(canonical_json(body)).hexdigest())
    with pytest.raises(CoreError):
        project_r4_resource_release(binding,claim,slot,receipt)
