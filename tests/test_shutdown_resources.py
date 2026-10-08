"""Public memory-only shutdown facts distinguish stop from durable release."""
import asyncio
from dataclasses import replace
import pytest

from nexus_connector_core import LaunchIntent, OpenOperation, SessionKey, ShutdownPolicy
from test_runtime import make_runtime, context, FakeClock


@pytest.mark.parametrize("ledger_mode", ["blocked", "failed"])
def test_stopped_resource_keeps_pending_release_visible_without_storage(tmp_path, ledger_mode):
    async def scenario():
        runtime, journal, factory = make_runtime(tmp_path, cleanup_budget_seconds=.01)
        ctx = context()
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"), ctx)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), ctx)
        key = SessionKey("srv", "exe", "session")
        assert runtime.shutdown_resources()[key]["process_state"] == "UNKNOWN"
        release = journal.release_owned_slot
        entered, restore = asyncio.Event(), asyncio.Event()
        async def unavailable(*args, **kwargs):
            entered.set()
            if ledger_mode == "failed" and not restore.is_set():
                raise OSError("Technical release failure")
            await restore.wait()
            return await release(*args, **kwargs)
        journal.release_owned_slot = unavailable
        try:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            await asyncio.wait_for(entered.wait(), 2)
            facts = runtime.shutdown_resources()
            assert facts[key] == {"process_state": "STOPPED", "release_pending": True}
            facts[key]["process_state"] = "changed by caller"
            assert runtime.shutdown_resources()[key]["process_state"] == "STOPPED"
            assert factory.open_count == 1
        finally:
            restore.set()
            async with asyncio.timeout(10):
                while runtime.shutdown_resources()[key]["release_pending"]:
                    await runtime.shutdown(ShutdownPolicy(0, 0))
                    await asyncio.sleep(.01)
            assert runtime.shutdown_resources()[key] == {"process_state": "STOPPED", "release_pending": False}
            journal.close()
    asyncio.run(scenario())


def test_expired_stopped_session_reconciles_release_after_eviction(tmp_path):
    async def scenario():
        clock = FakeClock(100)
        runtime, journal, factory = make_runtime(tmp_path, clock=clock,
            lease_grace_seconds=0, lease_poll_seconds=.01, cleanup_budget_seconds=.01)
        ctx = replace(context(), lease_deadline_monotonic=101)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"), ctx)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), ctx)
        key = SessionKey("srv", "exe", "session")
        release = journal.release_owned_slot
        restored = False
        async def unavailable(*args, **kwargs):
            if not restored:
                raise OSError("Technical release unavailable")
            return await release(*args, **kwargs)
        journal.release_owned_slot = unavailable
        try:
            clock.advance(2)
            async with asyncio.timeout(2):
                while runtime.shutdown_resources()[key]["process_state"] != "STOPPED":
                    await asyncio.sleep(.01)
            assert runtime.shutdown_resources()[key]["release_pending"] is True
            restored = True
            # A STOPPED observation precedes durable release and eviction.
            # Wait for their public completion, not a fixed number of polls.
            async with asyncio.timeout(10):
                while True:
                    report = await runtime.shutdown(ShutdownPolicy(0, 0))
                    if (not runtime.shutdown_resources()[key]["release_pending"]
                            and report.session_outcomes[key] == "already_closed"):
                        break
                    await asyncio.sleep(.01)
            assert runtime.shutdown_resources()[key] == {"process_state": "STOPPED", "release_pending": False}
            assert report.session_outcomes[key] == "already_closed"
            assert factory.open_count == 1
        finally:
            restored = True
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(scenario())
