"""Published control shapes are enforced by the same Core before native I/O."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from nexus_connector_core import (
    ControlOperation, CoreError, LaunchIntent, OpenOperation, OperationKey,
    ShutdownPolicy, build_executor_inventory_snapshot, get_control_targeting,
    get_runtime_catalog, validate_control_target, verify_executor_inventory_snapshot,
)
from test_runtime import context, make_runtime


def test_public_catalog_states_targeting_without_granting_build_readiness():
    catalog = get_runtime_catalog()
    assert catalog.format_version == 2
    by_id = {d.adapter_id: d for d in catalog.runtimes}
    assert get_control_targeting("codex_app_server", "turn.steer").native_turn_id == "required"
    pi = get_control_targeting("pi_rpc", "turn.steer")
    assert pi.native_turn_id == "forbidden" and pi.requires_active_run
    assert pi.steer_timing == "NEXT_TURN_BOUNDARY"
    assert not get_control_targeting("claude_stream", "turn.steer").supported
    assert by_id["claude_attach"].support_status == "registered_unqualified"
    assert all(not c.supported for c in by_id["claude_attach"].control_targeting)
    for descriptor in catalog.runtimes:
        for contract in descriptor.control_targeting:
            assert get_control_targeting(descriptor.adapter_id, contract.action) == contract


@pytest.mark.parametrize("adapter,verb,valid_target,bad_target", [
    ("codex_app_server", "steer", "current-turn", None),
    ("codex_app_server", "interrupt", "current-turn", ""),
    ("pi_rpc", "steer", None, "invented-turn"),
    ("pi_rpc", "interrupt", None, "invented-turn"),
    ("claude_stream", "interrupt", None, "invented-turn"),
])
def test_runtime_checks_public_contract_before_admitting_control(
        tmp_path, adapter, verb, valid_target, bad_target):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, adapter_id=adapter)
        authority = context(actions={"runtime.open", "runtime.close", "turn." + verb})
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", adapter), authority)
            await runtime.open(OpenOperation("open", "session", "epoch", prepared), authority)
            with pytest.raises(CoreError):
                await runtime.control(ControlOperation("bad", "session", verb,
                    text="change" if verb == "steer" else None,
                    expected_turn_id=bad_target), authority)
            assert not factory.native.sent
            assert await journal.get_receipt(OperationKey("srv", "exe", "bad")) is None
            receipt = await runtime.control(ControlOperation("good", "session", verb,
                text="change" if verb == "steer" else None,
                expected_turn_id=valid_target), authority)
            assert receipt.possible_effect
            assert factory.native.targets == [valid_target]
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_unknown_adapter_and_unsupported_control_do_not_fall_back():
    for adapter, action in (("unknown", "turn.steer"), ("pi_rpc", "invented"),
                            ("claude_stream", "turn.steer"), ("claude_attach", "turn.interrupt")):
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
            validate_control_target(adapter, action, None)


def test_snapshot_v2_binds_targeting_and_preserves_v1_history_bytes():
    snapshot = build_executor_inventory_snapshot([], server_id="s", executor_id="e",
                                                 producer_instance_id="p", publication_sequence=1)
    assert snapshot["snapshot_format_version"] == 2
    verify_executor_inventory_snapshot(snapshot)
    bad = deepcopy(snapshot)
    pi = next(row for row in bad["catalog"]["runtimes"] if row["adapter_id"] == "pi_rpc")
    pi["control_targeting"][0]["steer_timing"] = "IMMEDIATE"
    # An authenticated producer cannot publish a different control contract,
    # even if it recomputes the outer digest for its false claim.
    from nexus_connector_core.executor_inventory import _revision
    assert _revision(bad) != snapshot["inventory_revision"]
    bad["inventory_revision"] = _revision(bad)
    with pytest.raises(CoreError) as invalid:
        verify_executor_inventory_snapshot(bad)
    assert invalid.value.code == "VALIDATION_ERROR"
    path = Path(__file__).parent / "fixtures/executor-inventory-v1.json"
    original_bytes = path.read_bytes()
    old = json.loads(original_bytes)
    old_hash = old["inventory_revision"]
    with pytest.raises(CoreError) as incompatible:
        verify_executor_inventory_snapshot(old)
    assert incompatible.value.code == "VALIDATION_ERROR"
    verify_executor_inventory_snapshot(old, allow_historical=True)
    assert old_hash == "sha256:1f1808e558de7ead397e10ccedacb39d83e95c87145ffdf01ac3308273deb04a"
    assert _revision(old) == old_hash
    assert path.read_bytes() == original_bytes


def test_implemented_targeting_does_not_qualify_an_unknown_build(tmp_path, monkeypatch):
    import sys
    from nexus_connector_core import InstallationCandidate
    from nexus_connector_core.native.adapters import compatibility
    from nexus_connector_core.executor_inventory import _revision
    candidate = InstallationCandidate("codex_app_server", str(tmp_path / "codex"),
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "explicit", "selected", version="test", architecture="x86_64")
    def snapshot():
        return build_executor_inventory_snapshot([candidate], server_id="s", executor_id="e",
                                                  producer_instance_id="p", publication_sequence=1)
    original = snapshot()
    assert original["evidence"][0]["qualified_control_actions"] == []
    forged = deepcopy(original)
    forged["evidence"][0]["qualified_control_actions"] = ["turn.steer"]
    forged["inventory_revision"] = _revision(forged)
    with pytest.raises(CoreError):
        verify_executor_inventory_snapshot(forged)
    monkeypatch.setattr(compatibility, "QUALIFIED_CONTROL_BUILDS", {
        ("codex", "test", sys.platform, "x86_64", "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")})
    qualified = snapshot()
    assert qualified["evidence"][0]["qualified_control_actions"] == ["turn.interrupt", "turn.steer"]
    assert qualified["inventory_revision"] != original["inventory_revision"]
    verify_executor_inventory_snapshot(qualified)


def test_control_metadata_rejects_boolean_integer_aliases():
    from nexus_connector_core.executor_inventory import _revision
    snapshot = build_executor_inventory_snapshot([], server_id="s", executor_id="e",
                                                 producer_instance_id="p", publication_sequence=1)
    snapshot["catalog"]["runtimes"][0]["control_targeting"][0]["requires_active_run"] = 1
    snapshot["inventory_revision"] = _revision(snapshot)
    with pytest.raises(CoreError) as rejected:
        verify_executor_inventory_snapshot(snapshot)
    assert rejected.value.code == "VALIDATION_ERROR"
