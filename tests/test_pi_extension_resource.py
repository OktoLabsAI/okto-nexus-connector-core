import asyncio
from dataclasses import replace
import json
import os
import shutil
import time

import pytest

from nexus_connector_core import ExecutionContext
from nexus_connector_core.native_action_bridge import NativeActionGrant, ScopedNativeActionBridge
from nexus_connector_core.native_action_socket import NativeActionSocketService
from nexus_connector_core.pi_extension_resource import pi_extension_path


class Backend:
    def __init__(self):
        self.calls = []

    async def get_context(self, request, context):
        self.calls.append(("get", request.handoff_id, context.agent_id))
        return {"handoff_id": request.handoff_id, "status": "READY"}

    async def claim_handoff(self, request, context):
        self.calls.append(("claim", request.idempotency_key, context.agent_id))
        return {"handoff_id": request.handoff_id, "claim_epoch": 1}

    async def complete_handoff(self, request, context):
        self.calls.append(("complete", request.claim_epoch, context.agent_id))
        return {"handoff_id": request.handoff_id, "status": "COMPLETED"}


def _service(backend=None, context_override=None):
    backend = backend or Backend()
    actions = frozenset({"handoff.get", "handoff.claim", "handoff.complete"})
    expiry = time.monotonic() + 60
    grant = NativeActionGrant("native-cap:session", "srv", "exe", "bind",
                              "agent", "ws", "session", 6, 4, 5, expiry, actions)
    context = ExecutionContext("srv", "exe", "bind", "agent", "ws", 4, 5,
                               6, expiry, actions)
    return NativeActionSocketService(ScopedNativeActionBridge(backend, grant),
                                     lambda: context_override(context) if context_override else context), backend


async def _exchange(port, request):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()
    reply = json.loads(await asyncio.wait_for(reader.readline(), 5))
    writer.close()
    await writer.wait_closed()
    return reply


def test_pi_extension_is_local_package_resource():
    source = pi_extension_path()
    assert source.name == "index.js"
    assert json.loads(source.with_name("package.json").read_text())["type"] == "module"
    contents = source.read_text()
    assert "registerTool" in contents
    assert "tools/call" not in contents
    assert "fetch(" not in contents
    assert "createConnection" in contents


@pytest.mark.skipif(shutil.which("node") is None, reason="Node unavailable")
def test_pi_extension_real_local_socket_to_scoped_canonical_backend():
    script = r'''
import { pathToFileURL } from "node:url";
const { default: extension } = await import(pathToFileURL(process.argv[1]).href);
const tools = new Map();
extension({registerTool(tool) { tools.set(tool.name, tool); }});
if (tools.size !== 3) throw new Error("unexpected action set");
const get = tools.get("nexus_handoff_get");
let closed = false;
try { await get.execute("op", {handoff_id:"h"}); } catch { closed = true; }
if (!closed) throw new Error("missing host did not fail closed");
process.env.NEXUS_NATIVE_ACTION_PORT = process.argv[2];
process.env.NEXUS_NATIVE_CAPABILITY_REF = "native-cap:session";
process.env.NEXUS_NATIVE_SESSION_ID = "session";
for (const [name, params, expected] of [
  ["nexus_handoff_get", {handoff_id:"h"}, "READY"],
  ["nexus_handoff_claim", {handoff_id:"h",idempotency_key:"key"}, 1],
  ["nexus_handoff_complete", {handoff_id:"h",claim_epoch:1,result:{summary:"done"}}, "COMPLETED"],
]) {
  const result = await tools.get(name).execute("op", params);
  const observed = result.details.claim_epoch ?? result.details.status;
  if (observed !== expected) throw new Error(`wrong result for ${name}: ${observed}`);
}
process.env.NEXUS_NATIVE_CAPABILITY_REF = "native-cap:wrong";
closed = false;
try { await get.execute("op", {handoff_id:"h"}); } catch { closed = true; }
if (!closed) throw new Error("wrong capability accepted");
'''

    async def run():
        service, backend = _service()
        port = await service.start()
        try:
            clean_env = {key: value for key, value in os.environ.items()
                         if not key.startswith("NEXUS_NATIVE_")}
            process = await asyncio.create_subprocess_exec(
                "node", "--input-type=module", "-e", script,
                str(pi_extension_path()), str(port),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=clean_env,
            )
            out, err = await asyncio.wait_for(process.communicate(), 20)
            assert process.returncode == 0, (out, err)
            assert [call[0] for call in backend.calls] == ["get", "claim", "complete"]
            assert all(call[2] == "agent" for call in backend.calls)
        finally:
            await service.close()

    asyncio.run(run())


def test_socket_revoked_scope_and_mutating_lost_reply():
    class LostReply(Backend):
        async def claim_handoff(self, request, context):
            self.calls.append(("claim", request.idempotency_key, context.agent_id))
            raise RuntimeError("commit happened but acknowledgement disappeared")

    async def run():
        backend = LostReply()
        revision = [4]
        service, _ = _service(backend, lambda ctx: replace(
            ctx, authorization_revision=revision[0]))
        port = await service.start()
        try:
            request = {"action": "handoff.claim", "operation_id": "op",
                       "session_id": "session", "capability_ref": "native-cap:session",
                       "handoff_id": "h", "idempotency_key": "key"}
            revision[0] = 5
            denied = await _exchange(port, request)
            assert denied["code"] == "BINDING_NOT_AUTHORIZED"
            assert backend.calls == []
            revision[0] = 4
            unknown = await _exchange(port, request)
            assert unknown["code"] == "OUTCOME_UNKNOWN"
            assert unknown["possible_effect"] is True
            assert unknown["retry_safe"] is False
            assert len(backend.calls) == 1
        finally:
            await service.close()

    asyncio.run(run())


def test_socket_rejects_malformed_mcp_and_wrong_scope_before_backend():
    async def run():
        service, backend = _service()
        port = await service.start()
        try:
            base = {"action": "handoff.get", "operation_id": "op",
                    "session_id": "session", "capability_ref": "native-cap:session",
                    "handoff_id": "h"}
            requests = [
                b'{"action":"handoff.get","action":"handoff.claim"}\n',
                json.dumps({**base, "jsonrpc": "2.0"}).encode() + b"\n",
                json.dumps({**base, "capability_ref": "native-cap:other"}).encode() + b"\n",
                json.dumps({**base, "session_id": "other"}).encode() + b"\n",
                json.dumps({**base, "action": "tools/call"}).encode() + b"\n",
            ]
            for request in requests:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(request)
                await writer.drain()
                reply = json.loads(await asyncio.wait_for(reader.readline(), 5))
                assert reply["ok"] is False
                writer.close()
                await writer.wait_closed()
            assert backend.calls == []
        finally:
            await service.close()

    asyncio.run(run())
