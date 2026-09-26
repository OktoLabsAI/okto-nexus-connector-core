import asyncio
import math
import sqlite3
import time

import pytest

from nexus_connector_core import CoreError, ExecutionContext, Operation, OperationKey, OperationReceipt
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel
from nexus_connector_core.native.adapter_types import RuntimeCommandNotSent


def context():
    return ExecutionContext("srv", "exe", "bind", "agent", "ws", 1, 1, 7,
                            time.monotonic() + 60, frozenset({"turn.submit"}))


def test_dedupe_and_conflict(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        kernel = OperationKernel(journal)
        called = 0

        async def effect():
            nonlocal called
            called += 1
            return "native-1"

        operation = Operation("op1", "session", "turn.submit", {"text": "olá"})
        first = await kernel.execute(operation, context(), effect)
        second = await kernel.execute(operation, context(), effect)
        assert first == second
        assert called == 1
        with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
            await kernel.execute(Operation("op1", "session", "turn.submit",
                                           {"text": "different"}), context(), effect)
        journal.close()
    asyncio.run(run())


@pytest.mark.parametrize("bad_sample", [99.0, math.nan, math.inf])
def test_standalone_kernel_rejects_bad_monotonic_sample_before_admission(
    tmp_path, bad_sample,
):
    class RegressingClock:
        now = 100.0

        def monotonic(self):
            return self.now

        def wall_time(self):
            return self.now

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = RegressingClock()
        kernel = OperationKernel(journal, clock)
        auth = ExecutionContext("srv", "exe", "bind", "agent", "ws", 1, 1, 7,
                                120.0, frozenset({"turn.submit"}))
        called = 0

        async def effect():
            nonlocal called
            called += 1
            return "native"

        assert (await kernel.execute(Operation("first", "session", "turn.submit"),
                                     auth, effect)).stage == "SUBMITTED"
        clock.now = bad_sample
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await kernel.execute(Operation("after-rollback", "session", "turn.submit"),
                                 auth, effect)
        clock.now = 110.0
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await kernel.execute(Operation("after-recovery", "session", "turn.submit"),
                                 auth, effect)
        assert called == 1
        assert await journal.get_receipt(OperationKey("srv", "exe", "after-rollback")) is None
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("code", ["CAPABILITY_UNSUPPORTED", "STALE_TURN"])
def test_proven_not_sent_is_durable_safe_failure(tmp_path, code):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        kernel = OperationKernel(journal)
        operation = Operation("not-sent", "session", "turn.submit", {"text": "x"})

        async def effect():
            raise RuntimeCommandNotSent("rejected before write", code=code)

        with pytest.raises(CoreError, match=code) as exc:
            await kernel.execute(operation, context(), effect)
        assert exc.value.retry_safe and not exc.value.possible_effect
        journal.close()

        journal = SQLiteJournal(path)
        receipt = await OperationKernel(journal).execute(operation, context(), effect)
        assert receipt.stage == "FAILED"
        assert receipt.error_code == code
        assert not receipt.possible_effect and receipt.retry_safe
        journal.close()

    asyncio.run(run())


def test_explicit_retry_safe_core_error_is_recorded_as_not_sent(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        operation = Operation("safe-gate", "session", "turn.submit", {"text": "x"})

        async def effect():
            raise CoreError("NATIVE_VERSION_UNQUALIFIED", "native_gate",
                            retry_safe=True)

        with pytest.raises(CoreError, match="NATIVE_VERSION_UNQUALIFIED"):
            await OperationKernel(journal).execute(operation, context(), effect)
        receipt = await journal.get_receipt(OperationKey("srv", "exe", "safe-gate"))
        assert receipt.stage == "FAILED" and receipt.retry_safe
        assert not receipt.possible_effect
        journal.close()

    asyncio.run(run())


def test_possible_effect_is_not_replayed_after_reopen(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        operation = Operation("op2", "session", "turn.submit")
        from nexus_connector_core.protocol import intent_hash
        key = OperationKey("srv", "exe", operation.operation_id)
        await journal.admit(key, intent_hash(operation, context()),
                            operation.session_id)
        await journal.mark_possible_effect(key)
        journal.close()
        journal = SQLiteJournal(path)
        called = False

        async def effect():
            nonlocal called
            called = True
            return None

        receipt = await OperationKernel(journal).execute(operation, context(), effect)
        assert receipt.stage == "SUBMISSION_STARTED"
        assert receipt.possible_effect and not receipt.retry_safe
        assert not called
        journal.close()
    asyncio.run(run())


def test_legacy_unscoped_record_cannot_be_replayed(tmp_path):
    path = tmp_path / "journal.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE operations (operation_id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO operations VALUES ('legacy-op')")

    async def run():
        journal = SQLiteJournal(path)
        called = False

        async def effect():
            nonlocal called
            called = True
            return None

        operation = Operation("legacy-op", "session", "turn.submit")
        with pytest.raises(CoreError, match="LEGACY_OPERATION_UNSCOPED"):
            await OperationKernel(journal).execute(operation, context(), effect)
        assert not called
        journal.close()

    asyncio.run(run())


def test_terminal_receipt_cannot_be_downgraded_or_changed(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        key = OperationKey("srv", "exe", "op")
        await journal.admit(key, "hash", "session")
        await journal.mark_possible_effect(key)
        terminal = OperationReceipt("op", "hash", "SUCCEEDED", True, False,
                                    "session")
        assert await journal.record_receipt(key, terminal) == terminal
        late = OperationReceipt("op", "hash", "SUBMITTED", True, False,
                                "session", "native-1")
        effective = await journal.record_receipt(key, late)
        assert effective.stage == "SUCCEEDED"
        assert effective.native_id == "native-1"
        assert (await journal.record_receipt(key, OperationReceipt(
            "op", "hash", "RUNNING", True, False,
            "session"))).stage == "SUCCEEDED"
        with pytest.raises(CoreError, match="OPERATION_STAGE_CONFLICT"):
            await journal.record_receipt(key, OperationReceipt(
                "op", "hash", "FAILED", True, False, "session"))
        journal.close()

    asyncio.run(run())


def test_kernel_returns_terminal_if_native_event_wins_race(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        kernel = OperationKernel(journal)
        operation = Operation("op", "session", "turn.submit")
        key = OperationKey("srv", "exe", "op")

        async def effect():
            admitted = await journal.get_receipt(key)
            assert admitted.stage == "SUBMISSION_STARTED"
            await journal.record_receipt(key, OperationReceipt(
                "op", admitted.intent_hash, "SUCCEEDED", True, False,
                "session"))
            return "native-1"

        receipt = await kernel.execute(operation, context(), effect)
        assert receipt.stage == "SUCCEEDED" and receipt.native_id == "native-1"
        journal.close()

    asyncio.run(run())


def test_two_connections_cannot_downgrade_terminal_receipt(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        first = SQLiteJournal(path)
        second = SQLiteJournal(path)
        key = OperationKey("srv", "exe", "op")
        await first.admit(key, "hash", "session")
        await first.mark_possible_effect(key)
        terminal = OperationReceipt("op", "hash", "SUCCEEDED", True, False,
                                    "session")
        submitted = OperationReceipt("op", "hash", "SUBMITTED", True, False,
                                     "session", "native-id")
        await asyncio.gather(first.record_receipt(key, terminal),
                             second.record_receipt(key, submitted))
        result = await first.get_receipt(key)
        assert result.stage == "SUCCEEDED" and result.native_id == "native-id"
        first.close()
        second.close()

    asyncio.run(run())


def test_effect_imminent_admission_is_uncertain_before_native_call(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        key = OperationKey("srv", "exe", "core.internal.test")
        receipt, fresh = await journal.admit(key, "hash", "session",
                                             critical=True,
                                             effect_imminent=True)
        assert fresh
        assert receipt.stage == "SUBMISSION_STARTED"
        assert receipt.possible_effect and not receipt.retry_safe
        journal.close()

    asyncio.run(run())
