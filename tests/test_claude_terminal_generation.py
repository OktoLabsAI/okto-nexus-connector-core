import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nexus_connector_core.native.claude_terminal_generation import _request_for_prompt, _stream_started_at


def test_only_the_one_main_stream_can_confirm_generation():
    stamp = b"2026-02-20T03:33:20.123Z [DEBUG] "
    engine = stamp + b"[engine] turn 1 start\n"
    main = stamp + b"[API REQUEST] /v1/messages source=repl_main_thread\n"
    first = stamp + b"[API:timing] first byte after 18ms\n"
    other = stamp + b"[API REQUEST] /v1/messages source=title\n"
    finished = stamp + b"[engine] turn 1 end\n"
    before = 1771558400122
    assert _stream_started_at(engine + main, before) is None
    assert _stream_started_at(engine + main + first, before) == 1771558400123
    assert _stream_started_at(engine + main + first, before + 2) is None
    assert _stream_started_at(engine + other + main + first, before) is None
    assert _stream_started_at(engine + main + other + first, before) is None
    assert _stream_started_at(engine + main + first + other, before) is None
    assert _stream_started_at(engine + main + first + finished, before) is None
    assert _stream_started_at(engine + main + first + first, before) is None


def test_generation_correlates_the_prompt_hook_to_the_body_of_the_native_main_request(tmp_path):
    history = SimpleNamespace(session_uuid=str(uuid4()), workspace=str(tmp_path))
    prompt_id, request_id = str(uuid4()), str(uuid4())
    prompt_text = "Unicode prompt ✓"
    digest = hashlib.sha256(prompt_text.encode()).digest()
    message_hash = "a" * 64
    request = {"type": "api-request", "id": request_id, "version": "2.1.328", "tail": [message_hash],
               "querySource": "repl_main_thread", "sessionId": history.session_uuid}
    blob = {"type": "api-request-blob", "hash": message_hash, "sessionId": history.session_uuid,
            "message": {"role": "user", "content": [{"type": "text", "text": prompt_text}]}}
    user = {"type": "user", "sessionId": history.session_uuid, "cwd": history.workspace,
            "promptId": prompt_id, "version": "2.1.328", "entrypoint": "cli", "permissionMode": "plan",
            "promptSource": "typed", "isSidechain": False, "message": {"role": "user", "content": prompt_text}}

    def read(*records):
        return _request_for_prompt((json.dumps(item).encode() for item in reversed(records)), history, prompt_id, digest)

    assert read(user, blob, request) == request_id
    assert read(user, blob, request | {"tail": ["f" * 64]}) is None
    assert read(user | {"promptId": str(uuid4())}, blob, request) is None
    assert read(user, blob, request, {"type": "assistant", "sessionId": history.session_uuid}) is None
    assert read(user, blob, request, request | {"id": str(uuid4())}) is None
    assert read(user, blob, request | {"querySource": "title"}) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows delete-on-close diagnostic file")
def test_native_trace_file_is_retired_by_windows_even_on_immediate_host_exit(tmp_path):
    command = (
        "import os\n"
        "from nexus_connector_core.native.claude_terminal_generation import ClaudeGenerationTrace\n"
        "trace = ClaudeGenerationTrace()\n"
        "assert trace.path.is_file()\n"
        "print(trace.path, flush=True)\n"
        "os._exit(0)\n"
    )
    environment = os.environ | {name: str(tmp_path) for name in ("TMPDIR", "TEMP", "TMP")}
    result = subprocess.run([sys.executable, "-c", command], env=environment,
                            capture_output=True, text=True, check=True, timeout=15)
    trace_path = Path(result.stdout.strip())
    assert trace_path.parent.parent == tmp_path and trace_path.name == "stream.log"
    assert not trace_path.exists()
    trace_path.parent.rmdir()
