import asyncio
from contextlib import asynccontextmanager

import pytest

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.testing import (
    run_journal_conformance, run_journal_restart_conformance,
)


def test_reference_sqlite_journal_passes_reusable_port_scenarios(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "reference.db")
        try:
            trace = await run_journal_conformance(journal)
        finally:
            journal.close()
        assert trace.admitted_stage == "RECEIVED_DURABLE"
        assert trace.uncertain_stage == "OUTCOME_UNKNOWN"
        assert trace.resolved_stage == "SUCCEEDED"
        assert trace.terminal_event_stage == "SUCCEEDED"
        assert trace.not_sent_retry_safe
        assert trace.replay_sequences == (1, 2, 3, 4)
        assert trace.acknowledged_sequence == 4
        assert trace.compacted_gap_detected
        assert trace.session_claim_conflict_detected
        assert trace.claim_inventory_seen
        assert trace.process_birth_seen
        assert trace.owned_slot_seen

    asyncio.run(run())


def test_kit_detects_a_host_adapter_that_ignores_session_conflict(tmp_path):
    class FaultyHostAdapter:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def admit(self, key, intent_hash, session_id, **kwargs):
            if session_id.endswith("-other"):
                session_id = session_id.removesuffix("-other")
            return await self.inner.admit(key, intent_hash, session_id, **kwargs)

    async def run():
        journal = SQLiteJournal(tmp_path / "faulty.db")
        try:
            with pytest.raises(AssertionError, match="OPERATION_CONFLICT"):
                await run_journal_conformance(FaultyHostAdapter(journal))
        finally:
            journal.close()

    asyncio.run(run())


def test_kit_detects_a_host_adapter_that_ignores_session_claim(tmp_path):
    class FaultyHostAdapter:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def admit(self, key, intent_hash, session_id, **kwargs):
            kwargs.pop("claim_session", None)
            kwargs.pop("connection_generation", None)
            kwargs.pop("session_owner_generation", None)
            kwargs.pop("authorization_revision", None)
            kwargs.pop("configuration_revision", None)
            return await self.inner.admit(key, intent_hash, session_id, **kwargs)

    async def run():
        journal = SQLiteJournal(tmp_path / "faulty-claims.db")
        try:
            with pytest.raises(AssertionError, match="SESSION_CONFLICT"):
                await run_journal_conformance(FaultyHostAdapter(journal))
        finally:
            journal.close()

    asyncio.run(run())


def test_kit_detects_a_host_adapter_that_drops_open_generations(tmp_path):
    class FaultyHostAdapter:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def admit(self, key, intent_hash, session_id, **kwargs):
            kwargs.pop("connection_generation", None)
            kwargs.pop("session_owner_generation", None)
            kwargs.pop("authorization_revision", None)
            kwargs.pop("configuration_revision", None)
            return await self.inner.admit(key, intent_hash, session_id, **kwargs)

    async def run():
        journal = SQLiteJournal(tmp_path / "faulty-generations.db")
        try:
            with pytest.raises(AssertionError, match="opening_connection_generation"):
                await run_journal_conformance(FaultyHostAdapter(journal))
        finally:
            journal.close()

    asyncio.run(run())


def test_kit_detects_a_host_adapter_that_drops_owned_slots(tmp_path):
    class FaultyHostAdapter:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def reserve_owned_slot(self, key, session_id):
            return None

    async def run():
        journal = SQLiteJournal(tmp_path / "faulty-slots.db")
        try:
            with pytest.raises(AssertionError, match="SESSION_CONFLICT"):
                await run_journal_conformance(FaultyHostAdapter(journal))
        finally:
            journal.close()

    asyncio.run(run())


def test_reference_journal_passes_reusable_restart_scenarios(tmp_path):
    @asynccontextmanager
    async def open_journal():
        journal = SQLiteJournal(tmp_path / "restart.db")
        try:
            yield journal
        finally:
            journal.close()

    async def run():
        trace = await run_journal_restart_conformance(open_journal)
        assert trace.resumed_stage == "SUBMISSION_STARTED"
        assert trace.replay_sequences == (1, 2, 3)
        assert trace.acknowledged_sequence == 3

    asyncio.run(run())


def test_restart_kit_detects_an_ephemeral_host_adapter(tmp_path):
    opens = 0

    @asynccontextmanager
    async def open_ephemeral_journal():
        nonlocal opens
        opens += 1
        journal = SQLiteJournal(tmp_path / f"ephemeral-{opens}.db")
        try:
            yield journal
        finally:
            journal.close()

    async def run():
        with pytest.raises(AssertionError, match="operation/effect marker lost"):
            await run_journal_restart_conformance(open_ephemeral_journal)
        assert opens == 2

    asyncio.run(run())
