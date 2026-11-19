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
const events = [];
const facts = [];
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
const first = deferred();
const successor = deferred();
const input = deferred();
const session = {
  agent: {
    steeringQueue: { messages: [] },
    steer(message) { this.steeringQueue.messages.push(message); },
  },
  _steeringMessages: [],
  isStreaming: false,
  _emit(event) { events.push(event); },
  async _runAgentPrompt(completion) {
    this.isStreaming = true;
    this.agent.signal = new AbortController().signal;
    this._emit({ type: "agent_start" });
    try { await completion; } finally {
      this.isStreaming = false;
      this.agent.signal = undefined;
      this._emit({ type: "agent_settled" });
    }
  },
  async steer(text, images) {
    if (text === "delayed") await input.promise;
    await this._queueSteer(text, images);
  },
  async _queueSteer(text, images) {
    queued.push({ text, images });
    this._steeringMessages.push(text);
    this.agent.steer({ role: "user", content: [{ type: "text", text }] });
  },
};
const rpc = { source: "rpc" };
const owner = { session };
const received = [];
const replies = [];
const accept = fenceHostedRpcSteer(owner, (line) => {
  const frame = JSON.parse(line);
  (frame.type === "response" ? replies : facts).push(frame);
})((line) => received.push(JSON.parse(line)));
await assert.rejects(session.steer("idle", undefined, rpc), /selected by the steering command has ended/);
const run = session._runAgentPrompt(first.promise);
const runId = events.at(-1).hosted_pi_run_id;
const command = (op, text, target = runId) => ({ kind: "nexus_hosted_steer", operation_id: op, run_id: target, text });
await session.steer("during the first run", ["fixture-image"], rpc);
await session.steer(command("steer-1", "same text"), undefined, rpc);
await session.steer("same text", undefined, rpc);
const [, owned, equal] = session.agent.steeringQueue.messages;
session._emit({ type: "message_start", message: equal });
assert.equal(facts.length, 1);
session.agent.steeringQueue.messages.splice(1, 2);
session._emit({ type: "message_start", message: owned });
await session.steer(command("steer-2", "same text"), undefined, rpc);
const delayed = assert.rejects(session.steer("delayed", undefined, rpc), /selected by the steering command has ended/);
first.resolve();
await run;
const following = session._runAgentPrompt(successor.promise);
const successorId = events.at(-1).hosted_pi_run_id;
const abort = (id, target) => ({ type: "abort", id, nexus_expected_run_id: target });
accept(JSON.stringify(abort("old", runId)));
accept(JSON.stringify(abort("valid", successorId)));
assert.deepEqual(received, [abort("valid", successorId)]);
assert.deepEqual(replies.map(({ id, success, nexus_refused_before_abort }) => [id, success, nexus_refused_before_abort]), [
  ["old", false, true],
]);
input.resolve();
await delayed;
await assert.rejects(session.steer(command("wrong-run", "stale"), undefined, rpc), /target is stale/);
assert.deepEqual(session.agent.steeringQueue.messages.map(message => message.content[0].text), ["during the first run"]);
await session.steer("during the successor", undefined, rpc);
owner.session = {};
accept(JSON.stringify(abort("foreign-process", successorId)));
assert.deepEqual(received, [abort("valid", successorId)]);
assert.equal(replies.at(-1).id, "foreign-process");
await assert.rejects(session.steer("other session", undefined, rpc), /selected by the steering command has ended/);
successor.resolve();
await following;
assert.deepEqual(queued, [
  { text: "during the first run", images: ["fixture-image"] },
  { text: "same text", images: undefined },
  { text: "same text", images: undefined },
  { text: "same text", images: undefined },
  { text: "during the successor", images: undefined },
]);
assert.deepEqual(facts, [
  { type: "nexus_pi_steer", run_id: runId, operation_id: "steer-1", stage: "queued" },
  { type: "nexus_pi_steer", run_id: runId, operation_id: "steer-1", stage: "consumed" },
  { type: "nexus_pi_steer", run_id: runId, operation_id: "steer-2", stage: "queued" },
  { type: "nexus_pi_steer", run_id: runId, operation_id: "steer-2", stage: "discarded" },
]);
'''.replace("MODULE", json.dumps(module.as_uri()))
    result = subprocess.run([node, "--input-type=module", "-e", script],
                            check=False, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
