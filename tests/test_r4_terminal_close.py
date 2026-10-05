"""R4 close terminal facts are durable before return and survive waiter cancellation."""
import asyncio
import pytest
from nexus_connector_core import CloseOperation, CoreError, OperationKey, ShutdownPolicy
from test_runtime import make_runtime, FakeClock
from test_r4_runtime_leases import attempt, grant, open_session


@pytest.mark.parametrize("outcome", ["graceful", "forced", "unknown"])
def test_close_terminal_requires_confirmed_outcome(tmp_path, outcome):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        request = await attempt(runtime, clock)
        authority = (await runtime.install_r4_lease(request, grant(request))).context
        await open_session(runtime, authority)
        calls = []
        original = factory.native.close
        async def close():
            calls.append(1)
            await original()
            return outcome
        factory.native.close = close
        operation = CloseOperation("close", "session", "Done", ShutdownPolicy(1, 1))
        try:
            if outcome == "unknown":
                with pytest.raises(CoreError, match="OUTCOME_UNKNOWN"):
                    await runtime.close(operation, authority)
                expected = "OUTCOME_UNKNOWN"
            else:
                assert (await runtime.close(operation, authority)).stage == "SUCCEEDED"
                expected = "SUCCEEDED"
            stored = await journal.get_receipt(OperationKey("srv", "exe", "close"))
            assert stored.stage == expected
            assert await runtime.close(operation, authority) == stored
            assert len(calls) == 1
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_terminal_commit_is_retained_after_waiter_cancels(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        request = await attempt(runtime, clock)
        authority = (await runtime.install_r4_lease(request, grant(request))).context
        await open_session(runtime, authority)
        entered, release = asyncio.Event(), asyncio.Event()
        record = journal.record_receipt
        async def held_record(key, receipt):
            if key.operation_id == "close" and receipt.stage == "SUCCEEDED":
                entered.set()
                await release.wait()
            return await record(key, receipt)
        journal.record_receipt = held_record
        operation = CloseOperation("close", "session", "Done", ShutdownPolicy(2, 2))
        waiter = asyncio.create_task(runtime.close(operation, authority))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert factory.native.stopped
            stored = await journal.get_receipt(OperationKey("srv", "exe", "close"))
            assert stored.stage == "SUBMISSION_STARTED"
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            duplicate = asyncio.create_task(runtime.close(operation, authority))
            release.set()
            terminal = await asyncio.wait_for(duplicate, 2)
            assert terminal.stage == "SUCCEEDED"
            assert await journal.get_receipt(OperationKey("srv", "exe", "close")) == terminal
            assert await runtime.close(operation, authority) == terminal
        finally:
            release.set()
            await asyncio.gather(waiter, return_exceptions=True)
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


@pytest.mark.parametrize("storage_error", [False, True])
def test_owner_joins_after_observer_deadline_without_repeating_close(tmp_path, storage_error):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        request = await attempt(runtime, clock)
        authority = (await runtime.install_r4_lease(request, grant(request))).context
        await open_session(runtime, authority)
        entered, release = asyncio.Event(), asyncio.Event()
        record = journal.record_receipt
        async def held_record(key, receipt):
            if key.operation_id == "close" and receipt.stage == "SUCCEEDED":
                entered.set()
                await release.wait()
                if storage_error:
                    raise RuntimeError("Injected terminal storage failure")
            return await record(key, receipt)
        journal.record_receipt = held_record
        operation = CloseOperation("close", "session", "Done", ShutdownPolicy(.05, .05))
        observer = asyncio.create_task(runtime.close(operation, authority))
        owner = None
        try:
            await asyncio.wait_for(entered.wait(), 2)
            with pytest.raises(CoreError, match="OUTCOME_UNKNOWN"):
                await observer
            owner = asyncio.create_task(runtime.close(operation, authority, wait_for_completion=True))
            await asyncio.sleep(.15)
            assert not owner.done()
            release.set()
            if storage_error:
                with pytest.raises(RuntimeError, match="terminal storage failure"):
                    await asyncio.wait_for(owner, 2)
            else:
                receipt = await asyncio.wait_for(owner, 2)
                assert receipt.stage == "SUCCEEDED"
                assert await runtime.close(operation, authority, wait_for_completion=True) == receipt
        finally:
            release.set()
            await asyncio.gather(observer, *([owner] if owner else []), return_exceptions=True)
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())
