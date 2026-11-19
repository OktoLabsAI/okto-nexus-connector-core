import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, EventCursor
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native.adapter_types import HarnessEvent
from nexus_connector_core.native.codex_chat_facts import CODEX_CHAT_DELTA, valid_codex_chat_delta
from nexus_connector_core.native.event_ingest import NativeEventIngestor
from nexus_connector_core.native.redaction import NativeSecretRedactor, credential_values


def _event(kind, payload, *, native_event="message_update", phase=None):
    return HarnessEvent("session", "pi", kind, native_event,
                        "2026-09-25T00:00:00Z", payload,
                        turn_id="turn", delivery_phase=phase)


def test_split_known_and_generic_secrets_never_leave_raw_payload():
    redactor = NativeSecretRedactor(["secret-token"])
    first = redactor.scrub(_event("output_delta", {
        "assistantMessageEvent": {"type": "text_delta", "delta": "before sec"}}))
    second = redactor.scrub(_event("output_delta", {
        "assistantMessageEvent": {"type": "text_delta", "delta": "ret-token after Bear"}}))
    third = redactor.scrub(_event("output_delta", {
        "assistantMessageEvent": {"type": "text_delta", "delta": "er abc123 after"}}))
    terminal = redactor.scrub(_event("turn_completed", {},
                                    native_event="agent_settled", phase="terminal"))
    safe = "".join(event.output_text or "" for event in (first, second, third, terminal))
    assert "secret-token" not in safe
    assert "Bearer abc123" not in safe
    assert safe.count("[REDACTED]") >= 2
    for event in (first, second, third):
        assert event.payload["assistantMessageEvent"]["delta"] == "[NATIVE_TEXT_REDACTED]"


def test_nested_secret_keys_and_literal_variants_are_redacted():
    redactor = NativeSecretRedactor(["a\nb"])
    event = _event("error", {
        "headers": {"authorization": "Bearer abc123", "accessToken": "hidden"},
        "diagnostic": 'escaped a\\nb and literal a\nb and nxs_opaque',
    })
    safe = redactor.scrub(event)
    assert safe.payload["headers"]["authorization"] == "[REDACTED]"
    assert safe.payload["headers"]["accessToken"] == "[REDACTED]"
    assert "a\\nb" not in safe.payload["diagnostic"]
    assert "a\nb" not in safe.payload["diagnostic"]
    assert "nxs_opaque" not in safe.payload["diagnostic"]


def test_unknown_native_output_fields_are_withheld():
    event = _event("output_delta", {
        "vendor_blob": {"arbitrary": "fragment of an unknown credential",
                        "parts": ["secret", "-token"], "count": 2},
    })
    safe = NativeSecretRedactor().scrub(event)
    assert safe.payload == {"vendor_blob": {
        "arbitrary": "[NATIVE_TEXT_REDACTED]",
        "parts": ["[NATIVE_TEXT_REDACTED]", "[NATIVE_TEXT_REDACTED]"],
        "count": 2,
    }}


def _codex_delta(item, delta):
    return HarnessEvent("session", "codex", "output_delta", "item/agentMessage/delta",
        "2026-11-19T00:00:00Z", {"itemId": item, "delta": delta, "threadId": "thread", "turnId": "turn"},
        thread_id="thread", turn_id="turn", operation_id="operation")


def test_codex_fragments_keep_exact_item_and_mask_a_secret_across_interleaved_events():
    redactor = NativeSecretRedactor(["fixture-child-secret"])
    first = redactor.scrub(_codex_delta("item-one", "Public beginning. " * 4 + "fixture-child-"))
    reasoning = redactor.scrub(replace(_codex_delta("reason", "Private reasoning. " * 3),
        native_event="item/reasoning/textDelta"))
    another = redactor.scrub(_codex_delta("item-two", "Separate public answer. " * 4))
    last = redactor.scrub(_codex_delta("item-one", "secret after boundary. " * 4))
    facts = [event.payload[CODEX_CHAT_DELTA] for event in (first, another, last)]
    assert all(valid_codex_chat_delta(fact) for fact in facts)
    assert CODEX_CHAT_DELTA not in reasoning.payload
    assert [fact["item_id"] for fact in facts] == ["item-one", "item-two", "item-one"]
    combined = facts[0]["text"] + facts[2]["text"]
    assert combined.startswith("Public beginning.")
    assert "[REDACTED] after boundary." in combined
    assert "fixture-child-" not in combined and "Private reasoning" not in combined
    assert "Separate public answer" not in combined
    assert facts[1]["text"].startswith("Separate public answer.")
    assert first.payload["delta"] == first.payload["itemId"] == "[NATIVE_TEXT_REDACTED]"


def test_codex_fragments_require_native_identity_and_bound_utf8():
    redactor = NativeSecretRedactor(["child-credential"])
    malformed = _codex_delta("child-credential", "Public text. " * 8)
    assert CODEX_CHAT_DELTA not in redactor.scrub(malformed).payload
    spoofed = _codex_delta("item-other", "Public text. " * 8)
    spoofed.payload[CODEX_CHAT_DELTA] = {"revision": 1, "thread_id": "thread", "item_id": "wrong",
                                        "text": "wrong", "truncated": False}
    assert CODEX_CHAT_DELTA not in redactor.scrub(replace(spoofed, thread_id="stranger")).payload
    assert CODEX_CHAT_DELTA not in redactor.scrub(replace(spoofed, operation_id=None)).payload
    bounded = redactor.scrub(_codex_delta("item-large", "🍕" * 2100)).payload[CODEX_CHAT_DELTA]
    assert valid_codex_chat_delta(bounded) and bounded["truncated"]
    assert len(bounded["text"].encode()) == 4096


def test_redaction_scope_bounded_and_environment_selective():
    assert credential_values({"PATH": "important-path", "API_KEY": "secret",
                              "NEXUS_MCP_TOKEN_A": "cap"}) == ("secret", "cap")
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        NativeSecretRedactor(["x" * 16385])
    redactor = NativeSecretRedactor([])
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        redactor.scrub(_event("output_delta", {"delta": "nxs_" + "x" * 17000}))


def test_ingestor_commits_only_scrubbed_native_events(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "events.db")
        ingestor = NativeEventIngestor(
            journal, server_id="srv", executor_id="exe", session_id="session",
            stream_epoch="epoch", redactor=NativeSecretRedactor(["secret-token"]))
        for payload in ({"delta": "secret-"}, {"delta": "token"}):
            await ingestor.ingest(_event("output_delta", payload))
        await ingestor.ingest(_event("turn_completed", {}, phase="terminal"))
        cursor = EventCursor("srv", "exe", "session", "epoch")
        events = [event async for event in journal.events(cursor)]
        assert len(events) == 3
        assert all("secret-token" not in str(event.payload) for event in events)
        assert all(event.payload.get("delta") == "[NATIVE_TEXT_REDACTED]"
                   for event in events[:2])
        assert "[REDACTED]" in events[-1].payload["output_text"]
        journal.close()

    asyncio.run(run())
