import json

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.config_document import (
    apply_json_plan, plan_json_entry, plan_json_entry_removal,
)


def test_structural_merge_preserves_third_party_and_requires_owner_proof():
    original = (b'{"mcpServers":{"third-party":{"command":"other"}},'
                b'"unrelated":{"enabled":true}}')
    planned = plan_json_entry(
        original, section="mcpServers", entry_name="okto-nexus",
        proposed={"type": "http", "url": "https://nexus.test/mcp",
                  "capability_ref": "cap-1"})
    result = json.loads(apply_json_plan(planned, original))
    assert planned.changed_fields == ("capability_ref", "type", "url")
    assert result["mcpServers"]["third-party"] == {"command": "other"}
    assert result["unrelated"] == {"enabled": True}
    assert result["mcpServers"]["okto-nexus"]["capability_ref"] == "cap-1"
    with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
        plan_json_entry(apply_json_plan(planned, original), section="mcpServers",
                        entry_name="okto-nexus", proposed={"type": "http"})


def test_owner_provenance_and_revision_cas():
    owned = {"type": "http", "url": "https://old.test/mcp"}
    original = json.dumps({"mcpServers": {"okto-nexus": owned}}).encode()
    planned = plan_json_entry(original, section="mcpServers",
                              entry_name="okto-nexus", previously_owned=owned,
                              proposed={"type": "http", "url": "https://new.test/mcp"})
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        apply_json_plan(planned, original + b" ")
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_json_entry(original, section="mcpServers", entry_name="okto-nexus",
                        previously_owned={"type": "stdio"}, proposed=owned)
    assert json.loads(apply_json_plan(planned, original))["mcpServers"][
        "okto-nexus"]["url"] == "https://new.test/mcp"


def test_ownership_comparison_distinguishes_boolean_from_number():
    original = b'{"mcpServers":{"okto-nexus":{"enabled":true}}}'
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_json_entry(original, section="mcpServers", entry_name="okto-nexus",
                        previously_owned={"enabled": 1}, proposed={"enabled": False})


def test_plan_rejects_malformed_and_oversized_documents():
    for source in (b'{"a":1,"a":2}', b"[]", b"\xff",
                   b'{"mcpServers":{"okto-nexus":{"x":"\\ud800"}}}',
                   b"x" * (1024 * 1024 + 1)):
        with pytest.raises(CoreError):
            plan_json_entry(source, section="mcpServers", entry_name="okto-nexus",
                            proposed={"type": "http"})


def test_plan_maps_deep_json_recursion_to_profile_drift():
    deep = b'{"mcpServers":' + b'[' * 20000 + b'0' + b']' * 20000 + b'}'
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_json_entry(deep, section="mcpServers", entry_name="okto-nexus",
                        proposed={"type": "http"})


def test_plan_snapshots_input_and_idempotence():
    proposed = {"type": "http", "headers": {"X-Capability-Ref": "ref-1"}}
    plan = plan_json_entry(None, section="mcpServers", entry_name="okto-nexus",
                           proposed=proposed)
    proposed["headers"]["X-Capability-Ref"] = "mutated"
    result = apply_json_plan(plan, None)
    assert json.loads(result)["mcpServers"]["okto-nexus"]["headers"][
        "X-Capability-Ref"] == "ref-1"
    unchanged = plan_json_entry(result, section="mcpServers", entry_name="okto-nexus",
                                proposed=json.loads(result)["mcpServers"]["okto-nexus"],
                                previously_owned=json.loads(result)["mcpServers"]["okto-nexus"])
    assert not unchanged.changed
    assert unchanged.changed_fields == ()
    assert apply_json_plan(unchanged, result) == result


def test_owned_removal_preserves_third_party_and_requires_exact_proof():
    owned = {"type": "http", "url": "https://nexus.test/mcp"}
    original = json.dumps({"mcpServers": {"okto-nexus": owned,
                                          "third-party": {"command": "other"}},
                           "other": 1}).encode()
    plan = plan_json_entry_removal(original, section="mcpServers",
                                   entry_name="okto-nexus", previously_owned=owned)
    result = json.loads(apply_json_plan(plan, original))
    assert result == {"mcpServers": {"third-party": {"command": "other"}},
                      "other": 1}
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_json_entry_removal(original, section="mcpServers",
                                entry_name="okto-nexus",
                                previously_owned={"type": "stdio"})
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        plan_json_entry_removal(apply_json_plan(plan, original), section="mcpServers",
                                entry_name="okto-nexus", previously_owned=owned)
