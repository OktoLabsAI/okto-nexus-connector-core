"""Observed Codex 0.159 MCP permission forms require explicit one-call input."""
from copy import deepcopy

import pytest

from nexus_connector_core.native.native_inputs import ELICITATION, response_for, validate_request


def request():
    return {"method": ELICITATION, "params": {
        "threadId": "thread", "turnId": "turn", "serverName": "nexus_test", "mode": "form",
        "message": 'Allow the nexus_test MCP server to run tool "handoff_get"?',
        "_meta": {"codex_approval_kind": "mcp_tool_call", "persist": ["session", "always"]},
        "requestedSchema": {"type": "object", "properties": {}}}}


def test_empty_form_preserves_proposal_and_requires_explicit_one_call_response():
    original = request()
    frozen = deepcopy(original)
    validate_request(ELICITATION, original["params"])
    with pytest.raises(ValueError):
        response_for(original, None, approved=True)
    assert response_for(original, {"content": {}}, approved=True) == {"action": "accept", "content": {}}
    assert response_for(original, None, approved=False) == {"action": "decline"}
    assert original == frozen


@pytest.mark.parametrize("response", [
    {}, {"content": {"approve": True}},
    {"content": {}, "_meta": {"persist": "always"}},
    {"content": {}, "action": "accept"},
])
def test_empty_form_refuses_inferred_answers_and_persistent_permission(response):
    with pytest.raises(ValueError):
        response_for(request(), response, approved=True)


@pytest.mark.parametrize("schema", [
    {"type": "object", "properties": {}, "required": ["missing"]},
    {"type": "object", "properties": {}, "additionalProperties": True},
    {"type": "object", "properties": {}, "oneOf": []},
])
def test_empty_form_does_not_widen_unsupported_schema(schema):
    data = request()["params"]
    data["requestedSchema"] = schema
    with pytest.raises(ValueError):
        validate_request(ELICITATION, data)
