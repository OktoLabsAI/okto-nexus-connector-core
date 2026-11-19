"""The private Pi renderer authenticates both peers and exposes output only."""

import asyncio
from dataclasses import replace
from importlib.resources import files
import json
from pathlib import Path
import shutil

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.native.pi_renderer import PiRendererEndpoint


def test_private_pi_renderer_rejects_wrong_key_and_filters_terminal_controls():
    node = shutil.which("node")
    if node is None:
        pytest.skip("The private Pi renderer adapter runs on Node")
    module = Path(str(files("nexus_connector_core").joinpath("pi_extension", "hosted_renderer.js")))
    script = r'''
import assert from "node:assert/strict";
import { startHostedRenderer, TerminalOutputFilter } from MODULE;

const filter = new TerminalOutputFilter();
assert.equal(filter.filter("before\x1b]52;c;"), "before");
assert.equal(filter.filter("clipboard\x1b"), "");
assert.equal(filter.filter("\\after\x1b[31mred\x1b[0m\x1b[6n"), "after\x1b[31mred\x1b[0m");
assert.equal(filter.filter("\x9d8;;file:///x\x07link\x1bPpayload\x1b\\"), "link");

class NativeTranscript {
  constructor(owner, { terminal }) {
    assert.equal(owner.session, session);
    this.ui = { terminal };
    this.chatContainer = { children: [] };
    this.sessionManager = { buildContextEntries: () => [] };
    this.renderer = { render: () => terminal.columns === 300 ? ["x".repeat(70_000)] :
      ["\x1b]52;c;c2VjcmV0\x07the session\x1b[32m✓\x1b[0m"] };
  }
  mountInteractiveTui() {}
  renderSessionEntries() {}
  stop() {}
}
const session = { sessionId: "exact", subscribe: () => () => {} };
const port = await startHostedRenderer(NativeTranscript, { session }, "a".repeat(64));
console.log(port);
process.stdin.resume();
'''.replace('MODULE', json.dumps(module.as_uri()))

    async def run():
        proc = await asyncio.create_subprocess_exec(node, "--input-type=module", "-e", script,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            async with asyncio.timeout(10):
                banner = await proc.stdout.readline()
                assert banner, (await proc.stderr.read()).decode()
                target = PiRendererEndpoint(int(banner), "exact", "a" * 64)
                with pytest.raises(CoreError, match="NATIVE_UNAVAILABLE"):
                    async with replace(target, _key="b" * 64).attach(100, 40):
                        pytest.fail("An unrelated key attached to the renderer")
                with pytest.raises(CoreError, match="NATIVE_UNAVAILABLE"):
                    async with replace(target, session_id="sibling").attach(100, 40):
                        pytest.fail("A sibling session attached to the renderer")
                async with target.attach(300, 40) as over_limit:
                    assert await over_limit.read_output() is None
                async with target.attach(100, 40) as reader:
                    frame = await reader.read_output()
                    assert frame == "\x1b[2J\x1b[Hthe session\x1b[32m✓\x1b[0m".encode()
                    with pytest.raises(CoreError, match="NATIVE_UNAVAILABLE"):
                        async with target.attach(100, 40):
                            pytest.fail("A concurrent viewer replaced the active renderer")
        finally:
            if proc.returncode is None:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), 5)

    asyncio.run(run())


def test_private_pi_renderer_refuses_a_reflected_client_proof():
    async def run():
        observed = []

        async def reflect(reader, writer):
            try:
                writer.write(json.dumps({"type": "challenge", "revision": 1, "challenge": "a" * 64}).encode() + b"\n")
                await writer.drain()
                request = json.loads(await reader.readline())
                observed.append(request)
                writer.write(json.dumps({"type": "ready", "proof": request["proof"]}).encode() + b"\n")
                await writer.drain()
            finally:
                writer.close()

        async with await asyncio.start_server(reflect, "127.0.0.1", 0) as server:
            target = PiRendererEndpoint(server.sockets[0].getsockname()[1], "exact", "b" * 64)
            with pytest.raises(CoreError, match="NATIVE_UNAVAILABLE"):
                async with target.attach(100, 40):
                    pytest.fail("A peer reflected a client proof and was treated as the core-owned renderer")
        assert len(observed) == 1 and "b" * 64 not in json.dumps(observed[0])

    asyncio.run(run())
