"""Shared retry observation cannot multiply slow ledger calls or own effects."""
import asyncio
from types import SimpleNamespace

import pytest

from nexus_connector_core import CapacityRetryWaiter


def test_slow_revision_has_one_retained_producer_and_bounded_waiters():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def revision():
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return 1
        waiter = CapacityRetryWaiter(revision, max_waiters=4, poll_seconds=.01)
        tasks = [asyncio.create_task(waiter.wait(0)) for _ in range(4)]
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(RuntimeError, match='budget'):
            await waiter.wait(0)
        assert calls == 1
        closing = asyncio.create_task(waiter.aclose())
        assert await asyncio.wait_for(asyncio.gather(*tasks), 1) == [False] * 4
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not waiter._monitor.done()
        release.set()
        await asyncio.wait_for(waiter.aclose(), 1)
        assert calls == 1 and not await waiter.wait(waiter.version)
    asyncio.run(run())


@pytest.mark.parametrize('coarse_clock', [False, True])
def test_unchanged_revision_does_not_spin_on_repeated_admission_refusal(monkeypatch, coarse_clock):
    async def run():
        if coarse_clock:
            # Model the timer look-ahead used by Windows/Python 3.11 even on
            # hosts whose native monotonic clock has finer resolution.
            monkeypatch.setattr(asyncio.get_running_loop(), '_clock_resolution', .015625)
            monkeypatch.setattr('nexus_connector_core.capacity_waiter.time.get_clock_info',
                                lambda name: SimpleNamespace(resolution=.015625))
        value, calls = 1, 0
        async def revision():
            nonlocal calls
            calls += 1
            return value
        waiter = CapacityRetryWaiter(revision, poll_seconds=.01, recheck_seconds=.2)
        try:
            assert await asyncio.wait_for(waiter.wait(0), 1)
            task = asyncio.create_task(waiter.wait(waiter.version))
            await asyncio.sleep(.05)
            assert not task.done() and calls < 15
            value = 2
            assert await asyncio.wait_for(task, 1)
            # Lost external policy notifications still receive a bounded
            # periodic recheck, independent of capacity revision changes.
            assert await asyncio.wait_for(waiter.wait(waiter.version), 1)
        finally:
            await waiter.aclose()
    asyncio.run(run())


def test_cancelled_observer_does_not_cancel_shared_ledger_read():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def revision():
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return 7
        waiter = CapacityRetryWaiter(revision, poll_seconds=.01)
        first = asyncio.create_task(waiter.wait(0))
        second = asyncio.create_task(waiter.wait(0))
        await asyncio.wait_for(entered.wait(), 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert calls == 1 and not waiter._monitor.done()
        release.set()
        assert await asyncio.wait_for(second, 1)
        await waiter.aclose()
    asyncio.run(run())
