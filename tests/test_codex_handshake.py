"""Strict local Codex handshake and version-pinned wire shapes, without a model turn."""

import hashlib
import json
import sys
import time
from importlib.resources import files

import pytest
from jsonschema import Draft7Validator, ValidationError

from nexus_connector_core.native.adapter_types import HarnessCommand, NativeAdapterError
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector
from nexus_connector_core.native.adapters.compatibility import codex_initialize_observation


SCHEMA_SHA256 = "2719fccd25a97a7ce355497ca5e9123a63f6dce7f9f83724a5b73fd927811f59"


def _codex_schema():
    resource = files("nexus_connector_core.native").joinpath(
        "codex_app_server_0_157_0.schemas.json")
    raw = resource.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256
    return json.loads(raw)


def _validates(bundle, definition, value):
    Draft7Validator({"$ref": "#/definitions/" + definition,
                     "definitions": bundle["definitions"]}).validate(value)


def test_initialized_notification_precedes_thread_start(tmp_path):
    peer = tmp_path / "strict_codex_peer.py"
    peer.write_text("""
import json
import sys

initialized = False
client_name = None
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    with open("observed.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps(message) + "\\n")
    if method == "initialize":
        client_name = message["params"]["clientInfo"]["name"]
        print(json.dumps({"id": message["id"], "result": {
            "userAgent": client_name + "/0.157.0",
            "platformFamily": "windows", "platformOs": "windows"}}), flush=True)
    elif method == "initialized":
        initialized = True
    elif method == "thread/start":
        answer = ({"result": {"thread": {"id": "thread-1"}}} if initialized
                  else {"error": {"code": -32000, "message": "Not initialized"}})
        print(json.dumps({"id": message["id"], **answer}), flush=True)
""", encoding="utf-8")
    connector = CodexAppServerConnector(
        command=(sys.executable, str(peer)), cwd=str(tmp_path),
        client_info={"name": "core_test_host", "title": "Core Test Host",
                     "version": "1.2.3"}, handshake_timeout_s=3,
    )
    try:
        session = connector.start(owning_agent_id="agent")
        assert session.metadata["thread_id"] == "thread-1"
        assert session.compatibility_report["native_version"] == "0.157.0"
        assert not session.compatibility_report["capabilities_verified"]
        connector.send(session, HarnessCommand(session.session_id, "send_turn",
                                               {"text": "schema-only fixture"}))
        observed = tmp_path / "observed.jsonl"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            messages = [json.loads(line) for line in observed.read_text().splitlines()]
            if any(message.get("method") == "turn/start" for message in messages):
                break
            time.sleep(0.01)
        else:
            pytest.fail("synthetic peer did not receive turn/start")
        assert [message["method"] for message in messages[:4]] == [
            "initialize", "initialized", "thread/start", "turn/start"]
        assert "id" not in messages[1]
        schema = _codex_schema()
        _validates(schema, "ThreadStartParams", messages[2]["params"])
        _validates(schema, "TurnStartParams", messages[3]["params"])
        with pytest.raises(NativeAdapterError, match="pending or active turn") as rejected:
            connector.send(session, HarnessCommand(session.session_id, "send_turn",
                                                   {"text": "second turn"}))
        assert rejected.value.details["not_sent"] is True
        assert len([message for message in messages
                    if message.get("method") == "turn/start"]) == 1
    finally:
        connector.close()


def test_client_identity_is_trusted_and_user_agent_is_scoped():
    with pytest.raises(ValueError):
        CodexAppServerConnector(client_info={"name": "bad/name",
                                               "title": "Host", "version": "1"})
    assert codex_initialize_observation(
        {"userAgent": "another_host/0.157.0"},
        client_name="core_test_host")["native_version"] is None


def test_failed_initialize_retains_containment_for_factory_and_retry(tmp_path, monkeypatch):
    from nexus_connector_core.native.adapters import codex
    marker = tmp_path / 'first-start'
    script = tmp_path / 'retry_peer.py'
    script.write_text(
        'import json,sys,time\nfrom pathlib import Path\n'
        f'marker=Path({str(marker)!r})\n'
        'if not marker.exists():\n'
        ' marker.touch()\n sys.stdin.readline()\n time.sleep(60)\n'
        'for line in sys.stdin:\n'
        ' request=json.loads(line)\n'
        ' if request.get("method")=="initialize":\n'
        '  print(json.dumps({"id":request["id"],"result":{}}),flush=True)\n'
        ' elif request.get("method")=="thread/start":\n'
        '  print(json.dumps({"id":request["id"],"result":{"thread":{"id":"retry-thread"}}}),flush=True)\n',
        encoding='utf-8')
    transports = []
    original = codex._CodexTransport.start
    def start(transport):
        transports.append(transport)
        return original(transport)
    monkeypatch.setattr(codex._CodexTransport, 'start', start)
    connector = CodexAppServerConnector(command=[sys.executable, str(script)], cwd=str(tmp_path), env={}, handshake_timeout_s=1)
    assert connector.close() == 'unknown'
    try:
        with pytest.raises(NativeAdapterError):
            connector.start(owning_agent_id='subject')
        assert len(transports) == 1 and transports[0]._proc.poll() is not None
        assert connector.close() in ('graceful', 'forced', 'already_closed')
        session = connector.start(owning_agent_id='subject')
        assert session.metadata['thread_id'] == 'retry-thread'
        assert len(transports) == 2 and transports[1]._proc.poll() is None
        assert connector._startup_close_outcome == 'unknown'
        assert connector.close() in ('graceful', 'forced', 'already_closed')
        assert transports[1]._proc.poll() is not None
    finally:
        connector.close()


def test_pinned_turn_notification_shapes():
    schema = _codex_schema()
    turn = {"id": "turn-1", "items": [], "status": "inProgress"}
    _validates(schema, "TurnStartedNotification",
               {"threadId": "thread-1", "turn": turn})
    _validates(schema, "TurnCompletedNotification",
               {"threadId": "thread-1", "turn": {**turn, "status": "completed"}})
    with pytest.raises(ValidationError):
        _validates(schema, "TurnCompletedNotification",
                   {"threadId": "thread-1", "turn": {"id": "turn-1"}})
