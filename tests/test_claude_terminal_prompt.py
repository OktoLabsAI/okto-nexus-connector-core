"""Prompt authorization binds the vendor hook to one admitted operation."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.native.claude_terminal_prompt import ClaudeTerminalPromptGate


def _call(url, token, payload):
    request = Request(url, data=json.dumps(payload).encode(), headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def test_only_exact_prompt_and_scope_consume_the_host_authorization(tmp_path):
    session_uuid = str(uuid4())
    decided = []

    def authorize(operation_id):
        decided.append(operation_id)
        return True

    with ClaudeTerminalPromptGate(session_uuid, str(tmp_path), "plan", authorize) as gate:
        settings, env = gate.launch_settings()
        hook, = settings["hooks"]["UserPromptSubmit"][0]["hooks"]
        assert hook["onFailure"] == "block"
        variable, = hook["allowedEnvVars"]
        bearer = env[variable]
        assert bearer not in json.dumps(settings)
        url = hook["url"]
        body = {"hook_event_name": "UserPromptSubmit", "session_id": session_uuid,
                "permission_mode": "plan", "cwd": str(tmp_path), "prompt": "The exact input."}
        assert _call(url, bearer, body)[1]["decision"] == "block"
        gate.arm("server-turn-a", body["prompt"])
        assert _call(url, "wrong-token", body)[0] == 403
        for changes in ({"session_id": str(uuid4())}, {"cwd": str(tmp_path.parent)},
                        {"permission_mode": "default"}, {"prompt": "Different input."}):
            assert _call(url, bearer, body | changes)[1]["decision"] == "block"
        assert not decided
        assert _call(url, bearer, body) == (200, {})
        assert _call(url, bearer, body)[1]["decision"] == "block"
        with pytest.raises(CoreError, match="SESSION_CONFLICT"):
            gate.arm("server-turn-a", body["prompt"])
        assert decided == ["server-turn-a"]


def test_unavailable_issuer_does_not_leave_a_replayable_prompt(tmp_path):
    session_uuid = str(uuid4())

    def unavailable(_operation_id):
        raise OSError("Synthetic unavailable authorization store.")

    with ClaudeTerminalPromptGate(session_uuid, str(tmp_path), "plan", unavailable) as gate:
        settings, env = gate.launch_settings()
        hook, = settings["hooks"]["UserPromptSubmit"][0]["hooks"]
        body = {"hook_event_name": "UserPromptSubmit", "session_id": session_uuid,
                "permission_mode": "plan", "cwd": str(tmp_path), "prompt": "An uncertain request."}
        bearer = next(iter(env.values()))
        gate.arm("server-turn-uncertain", body["prompt"])
        assert _call(hook["url"], bearer, body) == (503, {})
        assert _call(hook["url"], bearer, body)[1]["decision"] == "block"
        with pytest.raises(CoreError, match="SESSION_CONFLICT"):
            gate.arm("server-turn-uncertain", body["prompt"])
