"""Off-loop executor semantics: saturation, cancellation, shutdown (PC01)."""

import asyncio
import threading
import time

import pytest

from nexus_connector_core.offloop import (
    ExecutorClosed, ExecutorFull, OffLoopExecutor,
)


def test_capacity_validation_rejects_bad_values():
    for kwargs in ({"normal_capacity": 0}, {"urgent_capacity": -1},
                   {"max_pending_bytes": True}, {"max_pending_bytes": "1"}):
        with pytest.raises(ValueError):
            OffLoopExecutor(**kwargs)


def test_submit_executes_off_loop_and_wakes_immediately():
    executor = OffLoopExecutor(name="t-wake")
    executor.start(lambda: object())
    try:
        loop_thread = threading.get_ident()
        seen = []

        def work(resource):
            seen.append(threading.get_ident())
            return 41

        async def run():
            future = executor.submit(work)
            return await asyncio.wait_for(future, timeout=2)

        result = asyncio.run(run())
        assert result == 41
        assert seen and seen[0] != loop_thread
    finally:
        executor.close()


def test_normal_saturation_raises_typed_backpressure_before_effect():
    executor = OffLoopExecutor(name="t-sat", normal_capacity=1,
                               urgent_capacity=2)
    release = threading.Event()
    started = threading.Event()
    executor.start(lambda: object())
    try:
        executor.submit_nowait(lambda resource: (started.set(), release.wait())[0])
        deadline = time.monotonic() + 2
        while not started.is_set() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert started.is_set()
        # The running item was dequeued; fill the single normal slot so the
        # next submission must be rejected before any effect.
        executor.submit_nowait(lambda resource: release.wait())

        async def run():
            with pytest.raises(ExecutorFull):
                executor.submit(lambda resource: None)
            # The urgent reserve still admits control work; a running unit
            # is never preempted, so completion follows the blocker's
            # release while admission itself already succeeded.
            urgent_done = []

            def control(resource):
                urgent_done.append(True)

            future = executor.submit(control, urgent=True)
            assert not future.done()
            release.set()
            await asyncio.wait_for(future, timeout=2)
            assert urgent_done == [True]

        asyncio.run(run())
    finally:
        release.set()
        executor.close()


def test_pending_byte_budget_rejects_oversized_normal_payloads():
    executor = OffLoopExecutor(name="t-bytes", max_pending_bytes=64)
    executor.start(lambda: object())
    try:
        release = threading.Event()
        executor.submit_nowait(lambda resource: release.wait(),
                               payload_bytes=64)
        time.sleep(0.05)

        async def run():
            with pytest.raises(ExecutorFull):
                executor.submit(lambda resource: None, payload_bytes=1)

        asyncio.run(run())
    finally:
        release.set()
        executor.close()


def test_cancellation_after_enqueue_still_completes_the_unit():
    executor = OffLoopExecutor(name="t-cancel")
    state = {"done": False}
    executor.start(lambda: object())
    try:
        release = threading.Event()

        def work(resource):
            release.wait(2)
            state["done"] = True

        async def run():
            future = executor.submit(work)
            await asyncio.sleep(0.05)
            future.cancel()
            assert future.cancelled()
            # The caller cancelled; the unit still runs to completion on the
            # worker (durable semantics), we just do not observe a result.
            release.set()
            deadline = time.monotonic() + 2
            while not state["done"] and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert state["done"]

        asyncio.run(run())
    finally:
        release.set()
        executor.close()


def test_exception_delivery_and_setup_failure():
    class Boom(RuntimeError):
        pass

    executor = OffLoopExecutor(name="t-exc")
    executor.start(lambda: object())
    try:
        async def run():
            future = executor.submit(lambda resource: (_ for _ in ()).throw(Boom()))
            with pytest.raises(Boom):
                await future

        asyncio.run(run())
    finally:
        executor.close()

    failing = OffLoopExecutor(name="t-setup")
    with pytest.raises(Boom):
        failing.start(lambda: (_ for _ in ()).throw(Boom()))
    assert failing.metrics()["worker_alive"] is False


def test_aclose_drains_and_closes_then_refuses_new_work():
    executor = OffLoopExecutor(name="t-close")
    executor.start(lambda: object())

    async def run():
        done = []
        future = executor.submit(lambda resource: done.append(True))
        await future
        assert (await executor.aclose(timeout=5)) == "closed"
        with pytest.raises(ExecutorClosed):
            executor.submit(lambda resource: None)

    asyncio.run(run())
    assert executor.metrics()["worker_alive"] is False


def test_repeated_start_close_cycles_do_not_leak_threads():
    for _ in range(5):
        executor = OffLoopExecutor(name="t-cycle")
        executor.start(lambda: object())
        executor.close()
        assert executor.metrics()["worker_alive"] is False
