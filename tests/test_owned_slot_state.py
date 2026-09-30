"""Historical slot state is distinct from liveness and absence."""
import asyncio
import sqlite3

import pytest
from nexus_connector_core import CoreError, OperationKey, OwnedSlotState, SessionKey, SQLiteOwnedSlotLedger
from nexus_connector_core.journal import SQLiteJournal


@pytest.mark.parametrize("factory", [SQLiteJournal, SQLiteOwnedSlotLedger])
def test_release_fact_survives_reopen_without_conflating_missing_or_active(tmp_path, factory):
    async def run():
        path = tmp_path / "slots.db"
        session = SessionKey("srv", "exe", "session")
        key = OperationKey("srv", "exe", "opening")
        store = factory(path)
        try:
            assert await store.owned_slot_state(session) is None
            if isinstance(store, SQLiteJournal):
                await store.admit(key, "intent", session.session_id, claim_session=True, effect_imminent=True)
            await store.reserve_owned_slot(key, session.session_id)
            assert await store.owned_slot_state(session) == OwnedSlotState(session, "opening", False)
            assert await store.owned_slot_state(SessionKey("other", "exe", "session")) is None
            assert await store.owned_slot_state(SessionKey("srv", "other", "session")) is None
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await store.release_owned_slot(OperationKey("srv", "exe", "wrong"), session.session_id)
            assert not (await store.owned_slot_state(session)).released
            await store.release_owned_slot(key, session.session_id)
            assert (await store.owned_slot_page()).reservations == ()
        finally:
            await store.aclose()
        reopened = factory(path)
        try:
            assert await reopened.owned_slot_state(session) == OwnedSlotState(session, "opening", True)
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await reopened.reserve_owned_slot(key, session.session_id)
            assert (await reopened.owned_slot_state(session)).released
        finally:
            await reopened.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("factory", [SQLiteJournal, SQLiteOwnedSlotLedger])
@pytest.mark.parametrize("invalid", [None, "session", SessionKey("", "exe", "session"),
                                     SessionKey("srv", "exe", ""), SessionKey("srv", "exe", 1)])
def test_state_query_rejects_invalid_scope(tmp_path, factory, invalid):
    async def run():
        store = factory(tmp_path / "slots.db")
        try:
            with pytest.raises(ValueError):
                await store.owned_slot_state(invalid)
        finally:
            await store.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("factory", [SQLiteJournal, SQLiteOwnedSlotLedger])
def test_corrupt_release_value_is_not_converted_to_true(tmp_path, factory):
    async def run():
        path = tmp_path / "slots.db"
        store = factory(path)
        session = SessionKey("srv", "exe", "session")
        try:
            key = OperationKey("srv", "exe", "open")
            if isinstance(store, SQLiteJournal):
                await store.admit(key, "intent", "session", claim_session=True, effect_imminent=True)
            await store.reserve_owned_slot(key, "session")
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE owned_slot_reservations SET released=2")
            with pytest.raises(CoreError, match="JOURNAL_UNAVAILABLE"):
                await store.owned_slot_state(session)
        finally:
            await store.aclose()
    asyncio.run(run())
