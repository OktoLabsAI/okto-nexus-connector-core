import asyncio

import pytest

from nexus_connector_core import CoreError, OperationKey, SQLiteOwnedSlotLedger
from nexus_connector_core.capacity_publication import CapacityChangePublisher


def test_durable_revision_tracks_ordinary_capacity_and_is_shared_by_adapters(tmp_path):
    async def run():
        first = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=2)
        second = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=2)
        key = OperationKey('server', 'executor', 'open')
        try:
            before = await second.capacity_revision()
            await first.reserve_owned_slot(key, 'session')
            opened = await second.capacity_revision()
            assert opened > before
            with pytest.raises(CoreError, match='SESSION_CONFLICT'):
                await second.reserve_owned_slot(key, 'session')
            assert await first.capacity_revision() == opened
            assert await second.release_owned_slot(key, 'session')
            released = await first.capacity_revision()
            assert released > opened
            assert not await second.release_owned_slot(key, 'session')
            assert await first.capacity_revision() == released
        finally:
            first.close()
            second.close()
    asyncio.run(run())


def test_paged_publications_refresh_and_do_not_starve_under_constant_changes():
    async def run():
        now, revision, output = [0.], [0], []
        async def snapshot():
            return revision[0], {f'b{i:03}': 'STALE_OBSERVATION' for i in range(100)}
        async def emit(**frame):
            output.append(frame)
        publisher = CapacityChangePublisher(boot_id='clock', snapshot=snapshot, emit=emit,
                                            clock=lambda: now[0], page_size=16)
        for _ in range(7):
            publisher.tick()
            await publisher._task
            revision[0] += 1
            now[0] += 1
        assert {f['binding_id'] for f in output} == {f'b{i:03}' for i in range(100)}
        assert all(f['reason'] == 'STALE_OBSERVATION' and f['boot_id'] == 'clock' for f in output)
        # Drain the changed page, then no unchanged observation is sent early.
        revision[0] -= 1
        for _ in range(6):
            publisher.tick()
            await publisher._task
            now[0] += .5
        total = len(output)
        publisher.tick()
        await publisher._task
        assert len(output) == total
        now[0] += 30
        publisher.tick()
        await publisher._task
        assert len(output) == total + 16
        await publisher.aclose()
    asyncio.run(run())


def test_slow_observation_retains_one_producer_and_close_does_not_orphan_it():
    async def run():
        entered, release, output = asyncio.Event(), asyncio.Event(), []
        count = 0
        async def snapshot():
            nonlocal count
            count += 1
            entered.set()
            await release.wait()
            return 1, {'binding': 'STALE_OBSERVATION'}
        async def emit(**frame):
            output.append(frame)
        publisher = CapacityChangePublisher(boot_id='clock', snapshot=snapshot, emit=emit)
        publisher.tick()
        await entered.wait()
        for _ in range(1000):
            publisher.tick()
        closing = asyncio.create_task(publisher.aclose())
        await asyncio.sleep(0)
        assert count == 1 and not closing.done()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not publisher._task.cancelled()
        release.set()
        await publisher.aclose()
        assert not output
    asyncio.run(run())


def test_failed_output_retries_and_oversized_snapshot_does_not_publish():
    async def run():
        now, output, fail, oversized = [0.], [], [True], [False]
        async def snapshot():
            return 2, {str(i): 'STALE_OBSERVATION' for i in range(257 if oversized[0] else 1)}
        async def emit(**frame):
            if fail[0]:
                raise RuntimeError('private diagnostic must not be exposed')
            output.append(frame)
        publisher = CapacityChangePublisher(boot_id='clock', snapshot=snapshot, emit=emit, clock=lambda: now[0])
        publisher.tick()
        await publisher._task
        assert publisher.last_error == 'RuntimeError' and not output
        fail[0], now[0] = False, 1
        publisher.tick()
        await publisher._task
        assert publisher.last_error is None and len(output) == 1
        oversized[0], now[0] = True, 2
        publisher.tick()
        await publisher._task
        assert publisher.last_error == 'ValueError' and len(output) == 1
        await publisher.aclose()
    asyncio.run(run())
