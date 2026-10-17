"""Independent observation is a retained lifecycle, not one parallel scan."""
import asyncio
from dataclasses import replace, FrozenInstanceError
import threading

import pytest

from nexus_connector_core import (IndependentInventoryObserver, HarnessObservationResult,
    CoreError, build_executor_inventory_snapshot, inventory_observation_fresh)
from test_executor_inventory import _candidate


def candidate(tmp_path, adapter):
    return replace(_candidate(str(tmp_path / adapter)), adapter_id=adapter)


def wire(batch, sequence=1):
    return build_executor_inventory_snapshot(batch.candidates, observations=batch.coverage(),
        server_id='server', executor_id='executor', producer_instance_id='owner',
        publication_sequence=sequence)


async def wait_for(predicate, observer):
    async def wait():
        while not predicate():
            batch = observer.snapshot()
            if predicate():
                break
            await observer.wait_changed(batch.revision)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.asyncio
async def test_stalled_pi_cannot_delay_repeated_sibling_observations(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    counts, active, maximum = {}, {}, {}
    now = [100.0]

    async def observe(adapter, cancel_requested):
        counts[adapter] = counts.get(adapter, 0) + 1
        active[adapter] = active.get(adapter, 0) + 1
        maximum[adapter] = max(maximum.get(adapter, 0), active[adapter])
        try:
            if adapter == 'pi_rpc':
                started.set()
                await release.wait()
            return HarnessObservationResult((candidate(tmp_path, adapter),))
        finally:
            active[adapter] -= 1

    observer = IndependentInventoryObserver(observe, refresh_seconds=3600, clock=lambda: now[0])
    initial = observer.request_refresh(('codex_app_server', 'claude_stream'))
    observer.start()
    observer.start()  # No duplicate startup workers.
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert await asyncio.wait_for(observer.wait_refresh(initial), 5)
        for _ in range(4):
            now[0] += 60
            frontier = observer.request_refresh(('codex_app_server', 'claude_stream'))
            assert await asyncio.wait_for(observer.wait_refresh(frontier), 5)
            snapshot = wire(observer.snapshot())
            assert inventory_observation_fresh(snapshot, 'claude_stream')
            assert inventory_observation_fresh(snapshot, 'codex_app_server')
            assert not inventory_observation_fresh(snapshot, 'pi_rpc')
            assert observer.snapshot().coverage()['pi_rpc']['state'] == 'PENDING'
        assert counts == {'claude_stream': 5, 'codex_app_server': 5, 'pi_rpc': 1}
        assert set(maximum.values()) == {1}
    finally:
        observer.begin_shutdown()
        release.set()
        await observer.aclose()


@pytest.mark.asyncio
async def test_other_publications_do_not_refresh_stalled_completed_observation(tmp_path):
    counts = {}
    release = asyncio.Event()
    now = [100.0]

    async def observe(adapter, cancel_requested):
        counts[adapter] = counts.get(adapter, 0) + 1
        if adapter == 'pi_rpc' and counts[adapter] == 2:
            await release.wait()
        return HarnessObservationResult((candidate(tmp_path, adapter),))

    observer = IndependentInventoryObserver(observe, refresh_seconds=3600, clock=lambda: now[0])
    initial = observer.request_refresh()
    observer.start()
    try:
        assert await asyncio.wait_for(observer.wait_refresh(initial), 5)
        published = observer.snapshot()
        observer.request_refresh(('pi_rpc',))
        for elapsed in (119, 120, 301):
            now[0] = 100 + elapsed
            frontier = observer.request_refresh(('claude_stream',))
            await asyncio.wait_for(observer.wait_refresh(frontier), 5)
            batch = observer.snapshot()
            snapshot = wire(batch)
            assert inventory_observation_fresh(snapshot, 'claude_stream')
            assert inventory_observation_fresh(snapshot, 'pi_rpc') is (elapsed < 120)
        assert batch.coverage()['pi_rpc'] == dict(state='FAILED', observation_age_ms=None,
                                                   error_code='OBSERVATION_EXPIRED')
        assert all(item.adapter_id != 'pi_rpc' for item in batch.candidates)
        # Published selection remains an immutable, exact earlier batch.
        assert published.coverage()['pi_rpc']['observation_age_ms'] == 0
        mutated = published.coverage()
        mutated['pi_rpc']['state'] = 'ABSENT'
        assert published.coverage()['pi_rpc']['state'] == 'PRESENT'
        with pytest.raises(FrozenInstanceError):
            published.revision = 999
    finally:
        observer.begin_shutdown()
        release.set()
        await observer.aclose()


@pytest.mark.asyncio
async def test_refresh_during_attempt_waits_for_next_start_and_coalesces(tmp_path):
    gates = [asyncio.Event(), asyncio.Event()]
    entered = [asyncio.Event(), asyncio.Event()]
    count = 0

    async def observe(adapter, cancel_requested):
        nonlocal count
        if adapter == 'pi_rpc':
            current = count
            count += 1
            entered[current].set()
            await gates[current].wait()
        return HarnessObservationResult((candidate(tmp_path, adapter),))

    observer = IndependentInventoryObserver(observe, refresh_seconds=3600)
    observer.start()
    try:
        await asyncio.wait_for(entered[0].wait(), 5)
        frontier = observer.request_refresh(('pi_rpc',))
        assert all(observer.request_refresh(('pi_rpc',)) == frontier for _ in range(100))
        wait = asyncio.create_task(observer.wait_refresh(frontier))
        wait.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait
        gates[0].set()
        await asyncio.wait_for(entered[1].wait(), 5)
        assert count == 2 and not observer.refresh_complete(frontier)
        gates[1].set()
        assert await asyncio.wait_for(observer.wait_refresh(frontier), 5)
        assert count == 2
    finally:
        observer.begin_shutdown()
        for gate in gates:
            gate.set()
        await observer.aclose()


@pytest.mark.asyncio
async def test_failure_is_explicit_and_retries_automatically_without_blocking_siblings(tmp_path):
    counts = {}
    async def observe(adapter, cancel_requested):
        counts[adapter] = counts.get(adapter, 0) + 1
        if adapter == 'pi_rpc' and counts[adapter] == 1:
            raise CoreError('PRIVATE_TOKEN_ABC', 'private', message='private path or provider data')
        return HarnessObservationResult((candidate(tmp_path, adapter),))
    observer = IndependentInventoryObserver(observe, refresh_seconds=.05, retry_seconds=.3,
                                            max_retry_seconds=.3)
    initial = observer.request_refresh()
    observer.start()
    try:
        assert await asyncio.wait_for(observer.wait_refresh(initial), 5)
        batch = observer.snapshot()
        assert batch.coverage()['pi_rpc']['state'] == 'FAILED'
        assert batch.coverage()['pi_rpc']['error_code'] == 'DISCOVERY_FAILED'
        assert 'PRIVATE' not in str(wire(batch)) and 'private' not in str(wire(batch))
        await wait_for(lambda: observer.snapshot().coverage()['pi_rpc']['state'] == 'PRESENT', observer)
        assert counts['claude_stream'] > 1 and counts['codex_app_server'] > 1
    finally:
        await observer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['type', 'mutable', 'adapter', 'fingerprint', 'overflow', 'raw_drop'])
async def test_invalid_adapter_result_cannot_poison_sibling_publication(tmp_path, fault):
    async def observe(adapter, cancel_requested):
        item = candidate(tmp_path, adapter)
        if adapter != 'pi_rpc':
            return HarnessObservationResult((item,))
        return {
            'type': None,
            'mutable': HarnessObservationResult([item]),
            'adapter': HarnessObservationResult((replace(item, adapter_id='claude_stream'),)),
            'fingerprint': HarnessObservationResult((replace(item, fingerprint='invalid'),)),
            'overflow': HarnessObservationResult((item,) * 129),
            'raw_drop': HarnessObservationResult((), (item,)),
        }[fault]
    observer = IndependentInventoryObserver(observe, refresh_seconds=3600, retry_seconds=3600,
                                            max_retry_seconds=3600)
    frontier = observer.request_refresh()
    observer.start()
    try:
        assert await asyncio.wait_for(observer.wait_refresh(frontier), 5)
        batch = observer.snapshot()
        assert batch.coverage()['pi_rpc']['error_code'] == 'INVALID_OBSERVATION'
        snapshot = wire(batch)
        assert inventory_observation_fresh(snapshot, 'claude_stream')
        assert len(snapshot['evidence']) == 2
    finally:
        await observer.aclose()


@pytest.mark.asyncio
async def test_canceled_close_waiter_does_not_release_a_running_thread(tmp_path):
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def blocking(cancel_requested):
        entered.set()
        release.wait()
        if cancel_requested():
            stopped.set()
        return HarnessObservationResult((candidate(tmp_path, 'pi_rpc'),))
    async def observe(adapter, cancel_requested):
        calls.append(adapter)
        if adapter == 'pi_rpc':
            return await asyncio.to_thread(blocking, cancel_requested)
        return HarnessObservationResult(())
    observer = IndependentInventoryObserver(observe, refresh_seconds=3600)
    observer.start()
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        before = observer.snapshot()
        closing = asyncio.create_task(observer.aclose())
        await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        with pytest.raises(RuntimeError):
            observer.request_refresh()
        with pytest.raises(RuntimeError):
            observer.start()
        assert not stopped.is_set()
        second_wait = asyncio.create_task(observer.aclose())
        await asyncio.sleep(.02)
        assert not second_wait.done() and calls.count('pi_rpc') == 1
    finally:
        release.set()
        await observer.aclose()
    await second_wait
    assert stopped.is_set()
    assert observer.snapshot().coverage()['pi_rpc']['state'] == 'PENDING'
    assert await observer.wait_changed(before.revision) is None


@pytest.mark.asyncio
async def test_new_owner_cannot_use_old_frontier_or_completed_evidence(tmp_path):
    async def observe(adapter, cancel_requested):
        return HarnessObservationResult((candidate(tmp_path, adapter),))
    first = IndependentInventoryObserver(observe)
    frontier = first.request_refresh()
    first.start()
    await asyncio.wait_for(first.wait_refresh(frontier), 5)
    await first.aclose()
    second = IndependentInventoryObserver(observe)
    try:
        assert all(row.state == 'PENDING' for row in second.snapshot().observations)
        with pytest.raises(ValueError):
            second.refresh_complete(frontier)
    finally:
        await second.aclose()


@pytest.mark.parametrize('interval', [0, -1, True, float('inf'), float('nan')])
def test_rejects_invalid_intervals(interval):
    with pytest.raises(ValueError):
        IndependentInventoryObserver(lambda *_: None, refresh_seconds=interval)


@pytest.mark.asyncio
async def test_completed_slow_observation_keeps_time_spent_discovering(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    now = [100.0]

    async def observe(adapter, cancel_requested):
        if adapter == 'pi_rpc':
            entered.set()
            await release.wait()
        return HarnessObservationResult((candidate(tmp_path, adapter),))

    observer = IndependentInventoryObserver(observe, refresh_seconds=3600, clock=lambda: now[0])
    frontier = observer.request_refresh(('pi_rpc',))
    observer.start()
    try:
        await asyncio.wait_for(entered.wait(), 5)
        now[0] += 125
        release.set()
        assert await asyncio.wait_for(observer.wait_refresh(frontier), 5)
        batch = observer.snapshot()
        assert batch.coverage()['pi_rpc']['state'] == 'PRESENT'
        assert batch.coverage()['pi_rpc']['observation_age_ms'] == 125_000
        assert not inventory_observation_fresh(wire(batch), 'pi_rpc')
        # The next completed attempt can restore freshness automatically.
        again = observer.request_refresh(('pi_rpc',))
        assert await asyncio.wait_for(observer.wait_refresh(again), 5)
        assert inventory_observation_fresh(wire(observer.snapshot()), 'pi_rpc')
    finally:
        release.set()
        await observer.aclose()


@pytest.mark.asyncio
async def test_cancelled_observation_child_does_not_silently_end_worker(tmp_path):
    counts = {}

    async def observe(adapter, cancel_requested):
        counts[adapter] = counts.get(adapter, 0) + 1
        if adapter == 'pi_rpc' and counts[adapter] == 1:
            child = asyncio.create_task(asyncio.sleep(3600))
            child.cancel()
            await child
        return HarnessObservationResult((candidate(tmp_path, adapter),))

    observer = IndependentInventoryObserver(observe, refresh_seconds=3600,
                                            retry_seconds=3600, max_retry_seconds=3600)
    initial = observer.request_refresh()
    observer.start()
    try:
        assert await asyncio.wait_for(observer.wait_refresh(initial), 5)
        batch = observer.snapshot()
        assert batch.coverage()['pi_rpc']['error_code'] == 'DISCOVERY_CANCELLED'
        assert inventory_observation_fresh(wire(batch), 'claude_stream')
        again = observer.request_refresh(('pi_rpc',))
        assert await asyncio.wait_for(observer.wait_refresh(again), 5)
        assert inventory_observation_fresh(wire(observer.snapshot()), 'pi_rpc')
        assert counts['pi_rpc'] == 2
    finally:
        await observer.aclose()
