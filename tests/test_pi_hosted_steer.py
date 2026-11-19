"""The hosted Pi steer fence survives asynchronous input handlers."""

import json
from importlib.resources import files
from pathlib import Path
import shutil
import subprocess

import pytest


def test_pi_rpc_input_handler_cannot_redirect_to_a_successor_run():
    node = shutil.which("node")
    if node is None:
        pytest.skip("The hosted Pi owner runs under Node")
    module = Path(str(files("nexus_connector_core").joinpath("pi_extension", "hosted_steer.js")))
    script = r'''
import assert from "node:assert/strict";
import { fenceHostedRpcSteer } from MODULE;

const queued = [];
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
const first = deferred();
const successor = deferred();
const input = deferred();
const session = {
  agent: {},
  isStreaming: false,
  async _runAgentPrompt(completion) {
    this.isStreaming = true;
    this.agent.signal = new AbortController().signal;
    try { await completion; } finally { this.isStreaming = false; this.agent.signal = undefined; }
  },
  async steer(text, images) {
    if (text === "delayed") await input.promise;
    await this._queueSteer(text, images);
  },
  async _queueSteer(text, images) { queued.push({ text, images }); },
};
const rpc = { source: "rpc" };
const owner = { session };
fenceHostedRpcSteer(owner);
await assert.rejects(session.steer("idle", undefined, rpc), /selected by the steering command has ended/);
const run = session._runAgentPrompt(first.promise);
await session.steer("during the first run", ["fixture-image"], rpc);
const delayed = assert.rejects(session.steer("delayed", undefined, rpc), /selected by the steering command has ended/);
first.resolve();
await run;
const following = session._runAgentPrompt(successor.promise);
input.resolve();
await delayed;
await session.steer("during the successor", undefined, rpc);
owner.session = {};
await assert.rejects(session.steer("other session", undefined, rpc), /selected by the steering command has ended/);
successor.resolve();
await following;
assert.deepEqual(queued, [
  { text: "during the first run", images: ["fixture-image"] },
  { text: "during the successor", images: undefined },
]);
'''.replace("MODULE", json.dumps(module.as_uri()))
    result = subprocess.run([node, "--input-type=module", "-e", script],
                            check=False, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
