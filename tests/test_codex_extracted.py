"""Extracted Codex transport against the preserved Nexus JSON-RPC peer."""

import sys
import threading
from pathlib import Path

from nexus_connector_core.native.adapter_types import HarnessCommand
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector


def test_codex_extracted_two_threads_do_not_cross(tmp_path):
    peer = Path(__file__).parent / "fixtures" / "codex_app_server_peer.py"
    connector = CodexAppServerConnector(
        command=(sys.executable, str(peer), str(tmp_path / "codex-log.jsonl")),
        cwd=str(tmp_path), handshake_timeout_s=5)
    seen = {}
    done = threading.Event()

    def consume(session_id):
        for event in connector.events_for_session(session_id):
            seen.setdefault(session_id, []).append(event)
            if event.kind == "turn_completed":
                if all(any(item.kind == "turn_completed" for item in values)
                       for values in seen.values()) and len(seen) == 2:
                    done.set()
                break

    try:
        first = connector.start(owning_agent_id="agent-one")
        second = connector.start(owning_agent_id="agent-two")
        readers = [threading.Thread(target=consume, args=(session.session_id,),
                                    daemon=True) for session in (first, second)]
        for reader in readers:
            reader.start()
        connector.send(first, HarnessCommand(first.session_id, "send_turn",
                                             {"text": "ECHO_ONE"}))
        connector.send(second, HarnessCommand(second.session_id, "send_turn",
                                              {"text": "ECHO_TWO"}))
        assert done.wait(timeout=8), {key: [e.native_event for e in value]
                                       for key, value in seen.items()}
        assert all(e.session_id == first.session_id for e in seen[first.session_id])
        assert all(e.session_id == second.session_id for e in seen[second.session_id])
        assert any(e.payload.get("delta") == "ECHO_ONE" for e in seen[first.session_id])
        assert any(e.payload.get("delta") == "ECHO_TWO" for e in seen[second.session_id])
    finally:
        connector.close()
