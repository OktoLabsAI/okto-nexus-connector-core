"""Shared recovery policy with real per-producer OS exclusion and SQLite."""
import asyncio
from dataclasses import replace
import threading
import uuid

import pytest

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import CoreError, OperationKey, SessionKey
from nexus_connector_core.native.process.launch_exclusion import HostLaunchExclusion
from nexus_connector_core.process_launch_control import ProcessLaunchController
from test_process_launch_storage import identity


def authority():
    pass


async def prepare(journal, launch):
    await journal.admit(OperationKey(launch.key.server_id, launch.key.executor_id,
        launch.opening_operation_id), 'intent', launch.key.session_id, claim_session=True,
        connection_generation=launch.connection_generation, session_owner_generation=launch.owner_generation,
        process_launch_identity=launch)
    await journal.mark_possible_effect(OperationKey(launch.key.server_id,
        launch.key.executor_id, launch.opening_operation_id))


def must_not_stop(_):
    pytest.fail('Unclaimed producer needs no container observation')


def test_recovered_unclaimed_intent_fences_late_worker_without_start(tmp_path):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        controller = ProcessLaunchController(journal, HostLaunchExclusion())
        calls = []
        try:
            await prepare(journal, launch)
            stopped = await controller.recover(launch, validate_authority=authority, stop_container=must_not_stop)
            assert stopped.state == 'STOPPED' and stopped.record.stop_proof == 'NEVER_CLAIMED'
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_FENCED'):
                await controller.produce(launch, validate_authority=authority, start=lambda: calls.append(1))
            assert calls == []
            assert await controller.recover(launch, validate_authority=authority, stop_container=must_not_stop) == stopped
        finally:
            await journal.aclose()
    asyncio.run(scenario())


def test_busy_or_cancelled_producer_cannot_release_its_slot_and_sibling_progresses(tmp_path):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        sibling = replace(launch, key=SessionKey('server','executor','sibling'),
            opening_operation_id='other', producer_id=uuid.uuid4().hex,
            container_id='Global\\nexus-core-'+uuid.uuid4().hex)
        controller = ProcessLaunchController(journal, HostLaunchExclusion())
        entered, finish, exited = threading.Event(), threading.Event(), threading.Event()
        def blocked_start():
            entered.set()
            try:
                assert finish.wait(10)
                return 'native'
            finally:
                exited.set()
        task = None
        try:
            await prepare(journal, launch)
            await prepare(journal, sibling)
            key = OperationKey('server','executor','open')
            await journal.reserve_owned_slot(key, 'session')
            task = asyncio.create_task(controller.produce(launch, validate_authority=authority, start=blocked_start))
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            busy = await controller.recover(launch, validate_authority=authority, stop_container=must_not_stop)
            assert busy.state == 'PRODUCER_BUSY'
            assert (await journal.owned_slot_page()).reservations
            # No global lock or serialized harness queue.
            assert await controller.produce(sibling, validate_authority=authority, start=lambda: 'sibling') == 'sibling'
            finish.set()
            assert await asyncio.to_thread(exited.wait, 10)
            # Worker may be releasing its OS gate after returning from start.
            for _ in range(100):
                recovered = await controller.recover(launch, validate_authority=authority,
                    stop_container=lambda _: 'STOPPED')
                if recovered.state != 'PRODUCER_BUSY':
                    break
                await asyncio.sleep(.01)
            assert recovered.state == 'STOPPED' and recovered.record.stop_proof == 'CONTAINER_STOPPED'
            assert (await journal.owned_slot_page()).reservations  # host owns capacity settlement
        finally:
            finish.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await journal.aclose()
    asyncio.run(scenario())


def test_claimed_crash_never_replays_and_requires_container_proof(tmp_path):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        controller = ProcessLaunchController(journal, HostLaunchExclusion())
        calls = []
        def crash():
            calls.append(1)
            raise RuntimeError('lost native result')
        try:
            await prepare(journal, launch)
            with pytest.raises(RuntimeError, match='lost native'):
                await controller.produce(launch, validate_authority=authority, start=crash)
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_ALREADY_CLAIMED') as error:
                await controller.produce(launch, validate_authority=authority, start=crash)
            assert error.value.possible_effect and not error.value.retry_safe and len(calls) == 1
            uncertain = await controller.recover(launch, validate_authority=authority,
                stop_container=lambda _: 'UNKNOWN')
            assert uncertain.state == 'CONTAINER_UNCERTAIN' and uncertain.record.state == 'FENCED'
            stopped = await controller.recover(launch, validate_authority=authority,
                stop_container=lambda _: 'STOPPED')
            assert stopped.state == 'STOPPED' and stopped.record.spawn_claimed
        finally:
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('action', ['produce', 'recover'])
def test_revoked_authority_cannot_claim_or_fence(tmp_path, action):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        controller = ProcessLaunchController(journal, HostLaunchExclusion())
        def revoked():
            raise CoreError('AGENT_REVOKED', 'launch')
        try:
            await prepare(journal, launch)
            with pytest.raises(CoreError, match='AGENT_REVOKED'):
                if action == 'produce':
                    await controller.produce(launch, validate_authority=revoked, start=lambda: pytest.fail('spawned'))
                else:
                    await controller.recover(launch, validate_authority=revoked, stop_container=must_not_stop)
            assert (await journal.get_process_launch(launch.key)).state == 'PREPARED'
        finally:
            await journal.aclose()
    asyncio.run(scenario())


def test_authority_lost_during_claim_prevents_native_start(tmp_path):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        controller = ProcessLaunchController(journal, HostLaunchExclusion())
        checks = []
        def revoked_after_storage():
            checks.append(1)
            if len(checks) == 2:
                raise CoreError('AGENT_REVOKED', 'launch')
        try:
            await prepare(journal, launch)
            with pytest.raises(CoreError, match='AGENT_REVOKED'):
                await controller.produce(launch, validate_authority=revoked_after_storage,
                    start=lambda: pytest.fail('Native start under expired authority'))
            # Claim is conservative after an interrupted frontier. Recovery
            # must fence it and obtain container proof, never assume no birth.
            assert (await journal.get_process_launch(launch.key)).state == 'CLAIMED'
            assert (await controller.recover(launch, validate_authority=authority,
                stop_container=lambda _: 'UNKNOWN')).state == 'CONTAINER_UNCERTAIN'
        finally:
            await journal.aclose()
    asyncio.run(scenario())
