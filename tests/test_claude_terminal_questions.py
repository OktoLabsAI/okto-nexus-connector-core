"""A native Claude hook accepts only an exact, current operator response."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from nexus_connector_core.models import CoreError, EffectNotSent
from nexus_connector_core.native import claude_terminal_prompt
from nexus_connector_core.native.claude_terminal_prompt import ClaudeTerminalPromptGate


@pytest.mark.parametrize("case", ["answer", "multi", "decline", "revoked", "expiry", "socket_loss"])
def test_claude_decision_is_bound_to_an_admitted_prompt(tmp_path, monkeypatch, case):
    session = str(uuid4())
    transcript = tmp_path / "claude-session.jsonl"
    if case == "expiry":
        monkeypatch.setattr(claude_terminal_prompt, "_DECISION_WAIT", 1)
    with ClaudeTerminalPromptGate(session, str(tmp_path), "plan", lambda _: True,
                                  observe_results=True, startup=("powershell", transcript),
                                  allow_questions=True) as gate:
        settings, env = gate.launch_settings()
        token = env["OKTO_CLAUDE_PROMPT_HOOK_TOKEN"]
        hooks = settings["hooks"]
        question_hook = hooks["PreToolUse"][0]["hooks"][0]
        assert question_hook["onFailure"] == "block"
        scope = {"session_id": session, "cwd": str(tmp_path), "permission_mode": "plan",
                 "transcript_path": str(transcript)}

        def post(url, kind, fields):
            request = Request(url, data=json.dumps({**scope, "hook_event_name": kind, **fields}).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        assert post(env["OKTO_CLAUDE_TERMINAL_START_URL"], "SessionStart", {"source": "resume"}) == {}
        pending_prompt = gate.arm("operation-1", "Run the fixture")
        assert post(hooks["UserPromptSubmit"][0]["hooks"][0]["url"], "UserPromptSubmit",
                    {"prompt": "Run the fixture", "prompt_id": "active-prompt"}) == {}
        assert pending_prompt.wait(1)
        tool_input = {"questions": [{"question": "Which fixture?", "header": "Fixture", "multiSelect": case == "multi",
            "options": [{"label": "Blue", "description": "First"}, {"label": "Green", "description": "Second"}]}]}
        payload = {"prompt_id": "active-prompt", "tool_name": "AskUserQuestion",
                   "tool_use_id": "native-tool-id", "tool_input": tool_input}

        def question(fields):
            return post(question_hook["url"], "PreToolUse", fields)["hookSpecificOutput"]

        assert question(payload | {"prompt_id": "different-prompt"})["permissionDecision"] == "deny"
        assert question(payload | {"agent_id": "child"})["permissionDecision"] == "deny"
        assert gate.take_decision() is None

        checked = []

        def fence(operation_id):
            checked.append(operation_id)
            if case == "revoked":
                raise EffectNotSent("The lease was revoked.", code="AGENT_REVOKED")

        if case == "socket_loss":
            complete = gate._complete_decision
            monkeypatch.setattr(gate, "_complete_decision", lambda current, _: complete(current, False))
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(question, payload)
            deadline = time.monotonic() + 4
            while (event := gate.take_decision()) is None:
                assert time.monotonic() < deadline
                time.sleep(.02)
            operation_id, request = event
            assert operation_id == "operation-1" and gate.take_decision() is None
            assert question(payload)["permissionDecision"] == "deny"
            answer = {"answers": {"Which fixture?": ["Blue", "Green"] if case == "multi" else "Blue"}}
            with pytest.raises(EffectNotSent, match="no longer waiting"):
                gate.reply_decision(request | {"local_generation": 7}, "accept", answer, fence)
            with pytest.raises(EffectNotSent, match="matching answer"):
                gate.reply_decision(request, "accept", {"answers": {"wrong": "Blue"}}, fence)
            if case == "expiry":
                assert pending.result()["permissionDecision"] == "deny"
                assert checked == []
            elif case == "revoked":
                with pytest.raises(EffectNotSent) as rejected:
                    gate.reply_decision(request, "accept", answer, fence)
                assert rejected.value.code == "AGENT_REVOKED"
                assert pending.result()["permissionDecision"] == "deny"
            elif case == "decline":
                gate.reply_decision(request, "decline", None, fence)
                assert pending.result()["permissionDecision"] == "deny"
            else:
                if case == "socket_loss":
                    with pytest.raises(CoreError, match="OUTCOME_UNKNOWN") as unknown:
                        gate.reply_decision(request, "accept", answer, fence)
                    assert unknown.value.possible_effect
                else:
                    gate.reply_decision(request, "accept", answer, fence)
                native_value = "Blue, Green" if case == "multi" else "Blue"
                assert pending.result()["updatedInput"] == tool_input | {"answers": {"Which fixture?": native_value}}
            with pytest.raises(EffectNotSent, match="no longer waiting"):
                gate.reply_decision(request, "accept", answer, fence)
            assert question(payload)["permissionDecision"] == "deny"
            assert checked == ([] if case == "expiry" else ["operation-1"])
