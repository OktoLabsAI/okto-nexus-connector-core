"""Local reconciliation obeys the same cardinality and ID bounds as NXL."""

import asyncio
import json
from importlib.resources import files

import pytest

from nexus_connector_core.models import ReconcileRequest
from nexus_connector_core.runtime import LocalRuntimeCore


class _JournalSpy:
    def __init__(self):
        self.lookups = []

    async def get_receipt(self, key):
        self.lookups.append(key)
        return None


def test_reconcile_bounds_match_bundled_nxl_contract():
    schema = json.loads(files("nexus_connector_core").joinpath(
        "contracts/nxl/v1/frame.schema.json").read_text(encoding="utf-8"))
    frame = next(item for item in schema["oneOf"]
                 if item.get("title") == "reconcile.request")
    assert schema["$defs"]["id"]["maxLength"] == 160
    assert frame["properties"]["operation_ids"]["maxItems"] == 256
    assert frame["properties"]["session_ids"]["maxItems"] == 256
    assert frame["properties"]["operation_ids"]["uniqueItems"]
    assert frame["properties"]["session_ids"]["uniqueItems"]


@pytest.mark.parametrize("candidate", [
    None,
    ReconcileRequest("", "exe"),
    ReconcileRequest("srv", ""),
    ReconcileRequest("s" * 161, "exe"),
    ReconcileRequest("srv", "exe", ("x", "x")),
    ReconcileRequest("srv", "exe", (), ("x", "x")),
    ReconcileRequest("srv", "exe", ("",)),
    ReconcileRequest("srv", "exe", (), ("x" * 161,)),
    ReconcileRequest("srv", "exe", tuple(str(i) for i in range(257))),
    ReconcileRequest("srv", "exe", (), tuple(str(i) for i in range(257))),
    ReconcileRequest("srv", "exe", ["x"]),
    ReconcileRequest("srv", "exe", (1,)),
])
def test_reconcile_rejects_noncontract_requests_before_journal_io(candidate):
    async def run():
        journal = _JournalSpy()
        runtime = LocalRuntimeCore(journal, object(), candidates={},
                                   workspace_roots={})
        with pytest.raises(ValueError):
            await runtime.reconcile(candidate)
        assert journal.lookups == []

    asyncio.run(run())


def test_reconcile_accepts_contract_maximum_and_preserves_order():
    async def run():
        journal = _JournalSpy()
        runtime = LocalRuntimeCore(journal, object(), candidates={},
                                   workspace_roots={})
        ids = tuple(f"op-{index}" for index in range(256))
        report = await runtime.reconcile(ReconcileRequest("srv", "exe", ids))
        assert len(report.receipts) == 256
        assert tuple(key.operation_id for key in journal.lookups) == ids

    asyncio.run(run())
