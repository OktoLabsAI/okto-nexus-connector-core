"""Run identical observable Journal-port scenarios on any host adapter.

The caller supplies an empty journal with safe test limits and owns cleanup.
No native process, network connection or canonical application store is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncContextManager, Callable
from uuid import uuid4

from ..models import (CoreError, EventCursor, OperationKey, OperationReceipt,
                      ProcessBirthEvidence, RuntimeEvent, SessionKey)
from ..ports import Journal


@dataclass(frozen=True, slots=True)
class JournalConformanceTrace:
    admitted_stage: str
    uncertain_stage: str
    resolved_stage: str
    terminal_event_stage: str
    not_sent_retry_safe: bool
    duplicate_fresh: bool
    watermark_before_gap_close: int
    watermark_after_gap_close: int
    acknowledged_sequence: int
    replay_sequences: tuple[int, ...]
    compacted_gap_detected: bool
    session_claim_conflict_detected: bool
    claim_inventory_seen: bool
    process_birth_seen: bool
    owned_slot_seen: bool
    lease_fence_seen: bool
    lease_revive_blocked: bool


@dataclass(frozen=True, slots=True)
class JournalRestartTrace:
    resumed_stage: str
    claimed_session_id: str
    replay_sequences: tuple[int, ...]
    acknowledged_sequence: int
    lease_connection_generation: int
    lease_revoked: bool


async def _expect_code(awaitable, code: str) -> None:
    try:
        await awaitable
    except CoreError as exc:
        if exc.code != code:
            raise AssertionError(f"expected {code}, got {exc.code}") from exc
    else:
        raise AssertionError(f"expected {code}")


async def run_journal_conformance(journal: Journal) -> JournalConformanceTrace:
    """Exercise admission, unknown, terminal, event gap/ACK/replay and prune.

    This kit compares observable semantics, not storage implementation. A
    host adapter must pass this unmodified; passing only the SQLite default
    is not evidence that an application's adapter conforms.
    """
    prefix = "core-conformance-" + uuid4().hex
    server, executor, session, epoch = (prefix + suffix for suffix in
                                         ("-srv", "-exe", "-session", "-epoch"))
    key = OperationKey(server, executor, prefix + "-operation")
    intent = "sha256:" + "1" * 64
    admitted, fresh = await journal.admit(key, intent, session)
    assert fresh and admitted.stage == "RECEIVED_DURABLE"
    same, duplicate_fresh = await journal.admit(key, intent, session)
    assert not duplicate_fresh and same == admitted
    await _expect_code(journal.admit(key, "sha256:" + "2" * 64, session),
                       "OPERATION_CONFLICT")
    await _expect_code(journal.admit(key, intent, session + "-other"),
                       "OPERATION_CONFLICT")
    started = await journal.mark_possible_effect(key)
    assert started.stage == "SUBMISSION_STARTED" and started.possible_effect
    uncertain = await journal.record_receipt(key, OperationReceipt(
        key.operation_id, intent, "OUTCOME_UNKNOWN", True, False, session))
    assert uncertain.stage == "OUTCOME_UNKNOWN" and not uncertain.retry_safe
    replay, replay_fresh = await journal.admit(key, intent, session)
    assert not replay_fresh and replay == uncertain
    resolved = await journal.record_receipt(key, OperationReceipt(
        key.operation_id, intent, "SUCCEEDED", True, False, session))
    assert resolved.stage == "SUCCEEDED"
    assert await journal.get_receipt(key) == resolved
    not_sent_key = OperationKey(server, executor, prefix + "-not-sent")
    not_sent_start, _ = await journal.admit(
        not_sent_key, intent, session, effect_imminent=True)
    assert not_sent_start.stage == "SUBMISSION_STARTED"
    not_sent = await journal.record_not_sent(not_sent_key, "SAFE_NO_WRITE")
    assert (not_sent.stage == "FAILED" and not_sent.retry_safe and
            not not_sent.possible_effect)
    terminal_key = OperationKey(server, executor, prefix + "-terminal")
    terminal_start, _ = await journal.admit(
        terminal_key, intent, session, effect_imminent=True)
    assert terminal_start.stage == "SUBMISSION_STARTED"

    cursor = EventCursor(server, executor, session, epoch)
    def event(sequence: int, text: str) -> RuntimeEvent:
        return RuntimeEvent(server, executor, session, epoch, sequence,
                            "text_delta", "conformance.delta", {"text": text})
    await journal.append_event(event(1, "one"))
    await journal.append_event(event(3, "three"))
    before = await journal.contiguous_watermark(cursor)
    assert before == 1
    await _expect_code(journal.acknowledge_events(cursor, 3), "EVENT_GAP")
    await journal.append_event(event(1, "one"))
    await _expect_code(journal.append_event(event(1, "changed")), "EVENT_CONFLICT")
    await journal.append_event(event(2, "two"))
    after = await journal.contiguous_watermark(cursor)
    assert after == 3
    await journal.append_event(RuntimeEvent(
        server, executor, session, epoch, 4, "turn_state",
        "conformance.terminal", {"delivery_phase": "terminal",
                                 "delivery_outcome": "success"},
        terminal_key.operation_id))
    terminal_receipt = await journal.get_receipt(terminal_key)
    assert terminal_receipt is not None and terminal_receipt.stage == "SUCCEEDED"
    sequences = tuple([item.sequence async for item in journal.events(cursor)])
    assert sequences == (1, 2, 3, 4)
    acknowledged = await journal.acknowledge_events(cursor, 4)
    assert acknowledged == 4
    compacted, _ = await journal.compact_acked(max_rows=128)
    assert compacted >= 4
    gap_detected = False
    try:
        _ = tuple([item async for item in journal.events(cursor)])
    except CoreError as exc:
        if exc.code != "EVENT_GAP":
            raise
        gap_detected = True
    assert gap_detected
    claim_session = session + "-claim"
    claim_key = OperationKey(server, executor, prefix + "-claim-open")
    claim_receipt, claim_fresh = await journal.admit(
        claim_key, intent, claim_session, claim_session=True,
        connection_generation=7, session_owner_generation=9,
        authorization_revision=4, configuration_revision=2)
    assert claim_fresh
    claim_duplicate, claim_fresh = await journal.admit(
        claim_key, intent, claim_session, claim_session=True,
        connection_generation=7, session_owner_generation=9,
        authorization_revision=4, configuration_revision=2)
    assert not claim_fresh and claim_duplicate == claim_receipt
    await _expect_code(journal.admit(
        OperationKey(server, executor, prefix + "-claim-other-open"),
        intent, claim_session, claim_session=True), "SESSION_CONFLICT")
    await journal.mark_possible_effect(claim_key)
    birth = ProcessBirthEvidence("linux", 1024,
                                 "boot-start:conformance:1", "linux_guardian")
    recorded_birth = await journal.record_process_birth(
        claim_key, claim_session, birth)
    assert recorded_birth.evidence == birth
    assert await journal.get_process_birth(
        SessionKey(server, executor, claim_session)) == recorded_birth
    await journal.reserve_owned_slot(claim_key, claim_session)
    await _expect_code(journal.reserve_owned_slot(
        claim_key, claim_session), "SESSION_CONFLICT")
    assert await journal.release_owned_slot(claim_key, claim_session) is True
    assert await journal.release_owned_slot(claim_key, claim_session) is False
    first_claim_page = await journal.claimed_sessions(server, executor, limit=1)
    assert len(first_claim_page.claims) == 1
    assert first_claim_page.claims[0].key.session_id == claim_session
    assert first_claim_page.claims[0].opening_operation_id == claim_key.operation_id
    assert first_claim_page.claims[0].opening_connection_generation == 7, (
        "opening_connection_generation lost by host adapter")
    assert first_claim_page.claims[0].opening_owner_generation == 9, (
        "opening_owner_generation lost by host adapter")
    later_claim_session = session + "-later-claim"
    await journal.admit(
        OperationKey(server, executor, prefix + "-later-claim-open"),
        intent, later_claim_session, claim_session=True)
    frozen = await journal.claimed_sessions(
        server, executor, high_water_rowid=first_claim_page.high_water_rowid)
    assert tuple(claim.key.session_id for claim in frozen.claims) == (claim_session,)
    fresh_page = await journal.claimed_sessions(server, executor)
    assert {claim.key.session_id for claim in fresh_page.claims} == {
        claim_session, later_claim_session}
    lease_session = SessionKey(server, executor, claim_session)
    opening_lease = await journal.get_session_lease(lease_session)
    assert opening_lease is not None and (
        opening_lease.connection_generation == 7 and
        opening_lease.owner_generation == 9 and
        opening_lease.authorization_revision == 4 and
        opening_lease.configuration_revision == 2 and
        not opening_lease.revoked), "opening lease fence lost by host adapter"
    renewed_lease = await journal.cas_session_lease(
        lease_session, expected_connection_generation=7,
        connection_generation=8, owner_generation=9,
        authorization_revision=5, configuration_revision=2, revoked=False)
    assert renewed_lease.connection_generation == 8
    await _expect_code(journal.cas_session_lease(
        lease_session, expected_connection_generation=7,
        connection_generation=9, owner_generation=9,
        authorization_revision=6, configuration_revision=2,
        revoked=False), "STALE_GENERATION")
    await _expect_code(journal.cas_session_lease(
        lease_session, expected_connection_generation=8,
        connection_generation=8, owner_generation=9,
        authorization_revision=4, configuration_revision=2,
        revoked=False), "STALE_GENERATION")
    revoked_lease = await journal.cas_session_lease(
        lease_session, expected_connection_generation=8,
        connection_generation=8, owner_generation=9,
        authorization_revision=6, configuration_revision=2, revoked=True)
    assert revoked_lease.revoked
    await _expect_code(journal.cas_session_lease(
        lease_session, expected_connection_generation=8,
        connection_generation=9, owner_generation=9,
        authorization_revision=7, configuration_revision=2,
        revoked=False), "STALE_GENERATION")
    # A claim admitted without lease evidence is a legacy claim: it reports
    # no durable fence and can never be cas'd from memory after the fact.
    legacy_key = OperationKey(server, executor, prefix + "-legacy-open")
    legacy_session = session + "-legacy-claim"
    await journal.admit(legacy_key, intent, legacy_session, claim_session=True)
    assert await journal.get_session_lease(
        SessionKey(server, executor, legacy_session)) is None
    await _expect_code(journal.cas_session_lease(
        SessionKey(server, executor, legacy_session),
        expected_connection_generation=1, connection_generation=2,
        owner_generation=1, authorization_revision=1,
        configuration_revision=1, revoked=False), "SESSION_UNKNOWN")
    return JournalConformanceTrace(admitted.stage, uncertain.stage,
                                   resolved.stage, terminal_receipt.stage,
                                   not_sent.retry_safe, duplicate_fresh, before,
                                   after, acknowledged, sequences, gap_detected,
                                   True, True, True, True, True, True)


async def run_journal_restart_conformance(
        open_journal: Callable[[], AsyncContextManager[Journal]]
) -> JournalRestartTrace:
    """Exercise durable port semantics across two independent reopen cuts.

    The caller supplies a factory that opens the *same* private backing store
    each time and closes every adapter on context exit. This kit does not
    assert process ownership or perform an actual crash/kill campaign.
    """
    prefix = "core-restart-" + uuid4().hex
    server, executor, session, epoch = (prefix + suffix for suffix in
                                         ("-srv", "-exe", "-session", "-epoch"))
    key = OperationKey(server, executor, prefix + "-open")
    intent = "sha256:" + "3" * 64
    cursor = EventCursor(server, executor, session, epoch)

    async with open_journal() as first:
        admitted, fresh = await first.admit(
            key, intent, session, claim_session=True,
            connection_generation=11, session_owner_generation=13,
            authorization_revision=1, configuration_revision=1)
        assert fresh and admitted.stage == "RECEIVED_DURABLE"
        started = await first.mark_possible_effect(key)
        assert started.stage == "SUBMISSION_STARTED" and started.possible_effect
        await first.reserve_owned_slot(key, session)
        birth = ProcessBirthEvidence("linux", 2048,
                                     "boot-start:conformance:2", "linux_guardian")
        birth_record = await first.record_process_birth(key, session, birth)
        for value in ("one", "two"):
            numbered = await first.record_event(RuntimeEvent(
                server, executor, session, epoch, 0, "text_delta",
                "conformance.restart", {"text": value}))
            assert numbered.sequence == (1 if value == "one" else 2)
        assert await first.acknowledge_events(cursor, 1) == 1

    async with open_journal() as second:
        resumed = await second.get_receipt(key)
        assert resumed == started, "operation/effect marker lost on reopen"
        lease = await second.get_session_lease(
            SessionKey(server, executor, session))
        assert lease is not None and lease.connection_generation == 11 and (
            lease.owner_generation == 13 and not lease.revoked), (
            "lease fence lost on reopen")
        advanced = await second.cas_session_lease(
            SessionKey(server, executor, session),
            expected_connection_generation=11, connection_generation=12,
            owner_generation=13, authorization_revision=2,
            configuration_revision=1, revoked=True)
        assert advanced.revoked and advanced.connection_generation == 12
        assert await second.get_process_birth(
            SessionKey(server, executor, session)) == birth_record
        duplicate, fresh = await second.admit(
            key, intent, session, claim_session=True,
            connection_generation=11, session_owner_generation=13)
        assert not fresh and duplicate == started
        await _expect_code(second.admit(
            OperationKey(server, executor, prefix + "-other-open"),
            intent, session, claim_session=True), "SESSION_CONFLICT")
        claims = await second.claimed_sessions(server, executor)
        assert len(claims.claims) == 1
        assert claims.claims[0].key.session_id == session
        assert claims.claims[0].opening_operation_id == key.operation_id
        assert claims.claims[0].opening_connection_generation == 11
        assert claims.claims[0].opening_owner_generation == 13
        await _expect_code(second.reserve_owned_slot(key, session),
                           "SESSION_CONFLICT")
        assert await second.contiguous_watermark(cursor) == 2
        assert tuple([item.sequence async for item in second.events(cursor)]) == (1, 2)
        assert await second.acknowledge_events(cursor, 1) == 1
        third_event = await second.record_event(RuntimeEvent(
            server, executor, session, epoch, 0, "text_delta",
            "conformance.restart", {"text": "three"}))
        assert third_event.sequence == 3

    async with open_journal() as third:
        assert await third.get_receipt(key) == started
        assert await third.get_process_birth(
            SessionKey(server, executor, session)) == birth_record
        assert await third.release_owned_slot(key, session) is True
        assert await third.acknowledge_events(cursor, 1) == 1
        replay = tuple([item.sequence async for item in third.events(cursor)])
        assert replay == (1, 2, 3)
        assert await third.contiguous_watermark(cursor) == 3
        assert await third.acknowledge_events(cursor, 3) == 3
        final_lease = await third.get_session_lease(
            SessionKey(server, executor, session))
        assert final_lease == advanced
        return JournalRestartTrace(started.stage, session, replay, 3,
                                   final_lease.connection_generation,
                                   final_lease.revoked)
