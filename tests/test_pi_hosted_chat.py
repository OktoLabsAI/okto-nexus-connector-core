"""The hosted Pi owner publishes chat only from its newly retained entry."""

import json
from importlib.resources import files
from pathlib import Path
import shutil
import subprocess

import pytest

from nexus_connector_core.native.pi_chat_facts import valid_pi_chat_fact


def test_hosted_pi_chat_requires_a_new_exact_entry_and_filters_content():
    node = shutil.which("node")
    if node is None:
        pytest.skip("The hosted Pi owner runs under Node")
    module = Path(str(files("nexus_connector_core").joinpath("pi_extension", "hosted_chat.js")))
    script = r'''
import assert from "node:assert/strict";
import { observeHostedPiChat } from MODULE;

let listener, leaf;
const writes = [];
const session = {sessionId: "native-pi-session", subscribe: fn => { listener = fn; }, sessionManager: {
  getLeafId: () => leaf?.id, getLeafEntry: () => leaf,
}};
const owner = {session};
observeHostedPiChat(owner, frame => writes.push(JSON.parse(frame)));
const text = value => ({type: "text", text: value});
const message = {role: "assistant", content: [text("visible"), {type: "thinking", thinking: "private"}, text("second")]};

listener({type: "message_end", message});
leaf = {type: "message", id: "abcdef01", message: {...message}};
await Promise.resolve();
assert.equal(writes.length, 0);

listener({type: "message_end", message});
leaf = {type: "message", id: "abcdef02", message};
assert.equal(writes.length, 0);
await Promise.resolve();
assert.deepEqual(writes, [{type: "nexus_pi_chat_message", revision: 1, native_session_id: "native-pi-session",
  entry_id: "abcdef02", role: "assistant", text: "visible\nsecond"}]);

listener({type: "message_end", message});
await Promise.resolve();
assert.equal(writes.length, 1);

const oversized = {role: "user", content: [text("あ".repeat(5000))]};
listener({type: "message_end", message: oversized});
leaf = {type: "message", id: "abcdef03", message: oversized};
await Promise.resolve();
assert.equal(writes.at(-1).text, null);

listener({type: "message_end", message});
leaf = {type: "message", id: "abcdef04", message};
owner.session = {};
await Promise.resolve();
assert.equal(writes.length, 2);
'''
    result = subprocess.run([node, "--input-type=module", "-e", script.replace("MODULE", json.dumps(module.as_uri()))],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr


def test_pi_chat_fact_rejects_unreviewed_identities_and_oversized_text():
    fact = {"revision": 1, "native_session_id": "native-session", "entry_id": "abcdef01",
            "role": "assistant", "text": "Published response"}
    assert valid_pi_chat_fact(fact)
    assert valid_pi_chat_fact(fact | {"text": None})
    for changes in ({"revision": True}, {"entry_id": "guess"}, {"role": "thinking"},
                    {"text": "あ" * 5000}, {"raw": "private"}, {"text": "\ud800"}):
        assert not valid_pi_chat_fact(fact | changes)
