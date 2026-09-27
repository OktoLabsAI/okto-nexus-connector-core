import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from nexus_connector_core import (CoreError, OperationKey, OwnedSlotPage,
                                  SQLiteOwnedSlotLedger)
from nexus_connector_core.testing import (
    run_owned_slot_conformance, run_owned_slot_restart_conformance,
)


def test_separate_handles_share_one_installation_slot_budget(tmp_path):
    async def run():
        path = tmp_path / "installation-slots.db"
        first = SQLiteOwnedSlotLedger(path, max_slots=1)
        second = SQLiteOwnedSlotLedger(path, max_slots=1)
        key_a = OperationKey("srv-a", "exe-a", "open-a")
        key_b = OperationKey("srv-b", "exe-b", "open-b")
        try:
            await first.reserve_owned_slot(key_a, "session-a")
            page = await second.owned_slot_page(limit=1)
            assert page.reservations[0].key.server_id == "srv-a"
            assert page.reservations[0].opening_operation_id == "open-a"
            assert page.next_after_rowid is None
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED") as denied:
                await second.reserve_owned_slot(key_b, "session-b")
            assert denied.value.retry_safe and not denied.value.possible_effect
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await second.release_owned_slot(key_b, "session-a")
            assert await second.release_owned_slot(key_a, "session-a") is True
            assert await first.release_owned_slot(key_a, "session-a") is False
            assert (await first.owned_slot_page()).reservations == ()
            await second.reserve_owned_slot(key_b, "session-b")
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await first.reserve_owned_slot(key_a, "session-a")
        finally:
            first.close()
            second.close()

        reopened = SQLiteOwnedSlotLedger(path, max_slots=1)
        try:
            assert reopened._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 1
        finally:
            reopened.close()

    asyncio.run(run())


def test_slot_ledger_rejects_relative_path_limits_and_policy_drift(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        SQLiteOwnedSlotLedger(Path("relative.db"))
    for kwargs in ({"max_slots": True}, {"max_slots": 0},
                   {"max_storage_bytes": 1024},
                   {"max_storage_bytes": 2**63}):
        with pytest.raises(ValueError, match="limits"):
            SQLiteOwnedSlotLedger(tmp_path / "invalid.db", **kwargs)

    async def run():
        path = tmp_path / "drift.db"
        first = SQLiteOwnedSlotLedger(path, max_slots=1)
        second = SQLiteOwnedSlotLedger(path, max_slots=2)
        try:
            await first.reserve_owned_slot(OperationKey("srv", "exe", "open-a"),
                                           "session-a")
            with pytest.raises(CoreError, match="PROFILE_DRIFT"):
                await second.reserve_owned_slot(
                    OperationKey("srv", "exe", "open-b"), "session-b")
            with pytest.raises(CoreError, match="PROFILE_DRIFT"):
                await second.release_owned_slot(
                    OperationKey("srv", "exe", "open-a"), "session-a")
            with pytest.raises(CoreError, match="PROFILE_DRIFT"):
                await second.owned_slot_page()
            assert first._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 1
            assert await first.release_owned_slot(
                OperationKey("srv", "exe", "open-a"), "session-a") is True
        finally:
            first.close()
            second.close()

    asyncio.run(run())


def test_slot_page_fences_new_reservations_and_validates_bounds(tmp_path):
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / "page.db", max_slots=3)
        try:
            first = OperationKey("srv-a", "exe", "open-a")
            second = OperationKey("srv-b", "exe", "open-b")
            third = OperationKey("srv-c", "exe", "open-c")
            await ledger.reserve_owned_slot(first, "one")
            await ledger.reserve_owned_slot(second, "two")
            page = await ledger.owned_slot_page(limit=1)
            assert len(page.reservations) == 1
            assert page.next_after_rowid is not None
            await ledger.reserve_owned_slot(third, "three")
            final = await ledger.owned_slot_page(
                after_rowid=page.next_after_rowid,
                high_water_rowid=page.high_water_rowid, limit=1)
            assert [item.key.session_id for item in final.reservations] == ["two"]
            assert final.next_after_rowid is None
            assert len((await ledger.owned_slot_page()).reservations) == 3
            for kwargs in ({"limit": 0}, {"limit": 4097},
                           {"after_rowid": -1}, {"high_water_rowid": True}):
                with pytest.raises(ValueError, match="owned-slot page"):
                    await ledger.owned_slot_page(**kwargs)
        finally:
            ledger.close()

    asyncio.run(run())


def test_installation_slot_ledger_passes_reusable_port_and_restart_kits(tmp_path):
    async def run():
        first = SQLiteOwnedSlotLedger(tmp_path / "port.db", max_slots=2)
        try:
            await run_owned_slot_conformance(first, max_slots=2)
        finally:
            first.close()

        @asynccontextmanager
        async def open_ledger():
            ledger = SQLiteOwnedSlotLedger(tmp_path / "restart.db", max_slots=1)
            try:
                yield ledger
            finally:
                ledger.close()

        await run_owned_slot_restart_conformance(open_ledger)

    asyncio.run(run())


def test_slot_kit_rejects_an_adapter_that_drops_reservations():
    class FaultyLedger:
        async def reserve_owned_slot(self, key, session_id):
            return None

        async def release_owned_slot(self, key, session_id):
            return True

        async def owned_slot_page(self, **kwargs):
            return OwnedSlotPage((), 0, None)

    with pytest.raises(AssertionError):
        asyncio.run(run_owned_slot_conformance(FaultyLedger(), max_slots=1))
