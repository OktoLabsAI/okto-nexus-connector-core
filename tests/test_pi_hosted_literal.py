"""The reviewed Pi owner must refuse request-rewriting hooks on literal input."""

import json
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

import pytest


def test_literal_requests_cannot_reach_prompt_hooks_or_an_active_turn():
    node = shutil.which("node")
    if node is None:
        pytest.skip("The hosted Pi owner runs under Node")
    module = Path(str(files("nexus_connector_core").joinpath("pi_extension", "hosted_literal.js")))
    script = r'''
import assert from "node:assert/strict";
import { fenceHostedRpcLiteral } from MODULE;

let activeHook;
const calls = [];
const session = {
  _extensionRunner: { hasHandlers: hook => hook === activeHook },
  async prompt(message, options) { calls.push({ message, options }); },
};
fenceHostedRpcLiteral(session);
const text = "/skill:sample café  ";
const literal = { kind: "nexus_hosted_literal", text };
const options = { source: "rpc", preflightResult() {} };
for (const hook of ["input", "before_agent_start", "context", "before_provider_request"]) {
  activeHook = hook;
  await assert.rejects(session.prompt(literal, options), /unavailable/);
}
activeHook = undefined;
for (const state of ["isStreaming", "isCompacting", "_isEmittingAgentSettled"]) {
  session[state] = true;
  await assert.rejects(session.prompt(literal, options), /unavailable/);
  session[state] = false;
}
await assert.rejects(session.prompt(literal, { source: "interactive" }), /malformed/);
await assert.rejects(session.prompt(literal, { ...options, streamingBehavior: "followUp" }), /malformed/);
await assert.rejects(session.prompt({ ...literal, extra: true }, options), /malformed/);
assert.equal(calls.length, 0);
await session.prompt(literal, options);
await session.prompt(text, options);
assert.deepEqual(calls, [
  { message: text, options: { ...options, expandPromptTemplates: false } },
  { message: text, options },
]);
'''.replace("MODULE", json.dumps(module.as_uri()))
    result = subprocess.run([node, "--input-type=module", "-e", script],
                            check=False, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
