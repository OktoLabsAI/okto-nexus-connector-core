"""Read approval is scoped to a reviewed, unchanged workspace file."""

import pytest

from nexus_connector_core.decision_bridge_r4 import native_request_action
from nexus_connector_core.models import EffectNotSent
from nexus_connector_core.native.claude_read_approval import review_claude_read
from test_claude_mcp_permissions import connector


def test_read_approval_rejects_external_files_links_and_replacements(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    file = root / "data.txt"
    file.write_text("original", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError):
        review_claude_read(root, {"file_path": str(outside)})
    reviewed, require_current = review_claude_read(root, {"file_path": str(file), "limit": 20})
    assert reviewed == {"file_path": "data.txt", "limit": 20}
    require_current()
    replacement = root / "replacement.txt"
    replacement.write_text("replacement", encoding="utf-8")
    replacement.replace(file)
    with pytest.raises(EffectNotSent, match="changed"):
        require_current()
    hard_link = root / "external-link.txt"
    hard_link.hardlink_to(outside)
    with pytest.raises(ValueError):
        review_claude_read(root, {"file_path": str(hard_link)})


@pytest.mark.parametrize("case", ["accept", "decline", "changed", "unreviewed"])
def test_stream_read_reuses_the_exact_reviewed_target(tmp_path, case):
    native = connector()
    native._cwd = str(tmp_path)
    native.claude_read_approval = case != "unreviewed"
    file = tmp_path / "reviewed.txt"
    file.write_text("review me", encoding="utf-8")
    writes = []

    def write(frame, *, before_write=None):
        if before_write is not None:
            before_write()
        writes.append(frame)

    native._write_json = write
    original = {"file_path": str(file), "offset": 1, "limit": 1}
    native._handle_permission_request({"request_id": "read-1", "request": {
        "subtype": "can_use_tool", "tool_name": "Read", "tool_use_id": "native-tool-1", "input": original,
    }})
    if case == "unreviewed":
        assert writes[0]["response"]["subtype"] == "error"
        assert not native._approval_requests
        return
    request = native._approval_requests["read-1"]["request"]
    assert native_request_action(request) == "approval.decide"
    assert request["params"]["input"] == original | {"file_path": "reviewed.txt"}
    if case == "changed":
        file.write_text("different content", encoding="utf-8")
        with pytest.raises(EffectNotSent, match="changed"):
            native.reply_native_approval("session", request, "accept")
        assert len(writes) == 1 and writes[0]["response"]["response"]["behavior"] == "deny"
        return
    native.reply_native_approval("session", request, case)
    answer = writes[0]["response"]["response"]
    if case == "accept":
        assert answer == {"behavior": "allow", "updatedInput": original}
    else:
        assert answer["behavior"] == "deny" and "updatedInput" not in answer
