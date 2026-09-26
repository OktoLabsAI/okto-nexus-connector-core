"""Reusable durable owned-slot port scenarios for trusted hosts."""

from __future__ import annotations

from typing import AsyncContextManager, Callable
from uuid import uuid4

from ..models import CoreError, OperationKey, SessionKey
from ..ports import OwnedSlotLedger


async def _expect_code(awaitable, code: str) -> None:
    try:
        await awaitable
    except CoreError as exc:
        if exc.code != code:
            raise AssertionError(f"expected {code}, got {exc.code}") from exc
    else:
        raise AssertionError(f"expected {code}")


async def run_owned_slot_conformance(ledger: OwnedSlotLedger, *,
                                     max_slots: int) -> None:
    """Exercise atomic capacity, identity and release on an empty ledger."""
    if type(max_slots) is not int or not 1 <= max_slots <= 32:
        raise ValueError("conformance max_slots must be 1..32")
    prefix = "core-slot-" + uuid4().hex
    keys = [OperationKey(prefix, "exe", f"open-{index}")
            for index in range(max_slots + 1)]
    sessions = [f"{prefix}-session-{index}"
                for index in range(max_slots + 1)]
    for index in range(max_slots):
        await ledger.reserve_owned_slot(keys[index], sessions[index])
    first_page = await ledger.owned_slot_page(limit=1)
    observed = list(first_page.reservations)
    next_after = first_page.next_after_rowid
    for _ in range(max_slots):
        if next_after is None:
            break
        page = await ledger.owned_slot_page(
            after_rowid=next_after,
            high_water_rowid=first_page.high_water_rowid, limit=1)
        observed.extend(page.reservations)
        next_after = page.next_after_rowid
    assert next_after is None
    assert {(item.key, item.opening_operation_id) for item in observed} == {
        (SessionKey(prefix, "exe", sessions[index]), keys[index].operation_id)
        for index in range(max_slots)}
    try:
        await ledger.owned_slot_page(limit=0)
    except ValueError:
        pass
    else:
        raise AssertionError("owned-slot page accepted an invalid limit")
    await _expect_code(ledger.reserve_owned_slot(keys[max_slots],
                                                 sessions[max_slots]),
                       "CAPACITY_EXCEEDED")
    await _expect_code(ledger.reserve_owned_slot(keys[0], sessions[0]),
                       "SESSION_CONFLICT")
    await _expect_code(ledger.release_owned_slot(keys[max_slots], sessions[0]),
                       "SESSION_CONFLICT")
    assert await ledger.release_owned_slot(keys[0], sessions[0]) is True
    assert await ledger.release_owned_slot(keys[0], sessions[0]) is False
    active = await ledger.owned_slot_page()
    assert SessionKey(prefix, "exe", sessions[0]) not in {
        item.key for item in active.reservations}
    await ledger.reserve_owned_slot(keys[max_slots], sessions[max_slots])
    for index in range(1, max_slots + 1):
        assert await ledger.release_owned_slot(
            keys[index], sessions[index]) is True


async def run_owned_slot_restart_conformance(
        open_ledger: Callable[[], AsyncContextManager[OwnedSlotLedger]]) -> None:
    """Check one-slot occupancy through independent close/reopen boundaries."""
    prefix = "core-slot-restart-" + uuid4().hex
    first = OperationKey(prefix, "exe", "open-first")
    second = OperationKey(prefix, "exe", "open-second")
    async with open_ledger() as ledger:
        await ledger.reserve_owned_slot(first, prefix + "-first")
    async with open_ledger() as ledger:
        await _expect_code(ledger.reserve_owned_slot(
            second, prefix + "-second"), "CAPACITY_EXCEEDED")
        page = await ledger.owned_slot_page()
        assert len(page.reservations) == 1
        assert page.reservations[0].opening_operation_id == first.operation_id
        assert await ledger.release_owned_slot(first, prefix + "-first") is True
    async with open_ledger() as ledger:
        await ledger.reserve_owned_slot(second, prefix + "-second")
        assert await ledger.release_owned_slot(second, prefix + "-second") is True
