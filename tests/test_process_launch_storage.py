"""Durable launch CAS never implies execution or physical slot release."""
import asyncio
from dataclasses import replace
import sqlite3

import pytest

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import CoreError, OperationKey, ProcessBirthEvidence, SessionKey
from nexus_connector_core.process_launch import ProcessLaunchIdentity


def identity(platform='win32'):
    containment, container = {
        'win32': ('windows_job', 'Global\\nexus-core-'+'a'*32),
        'linux': ('linux_guardian', 'linux-guardian:'+'a'*32),
        'darwin': ('darwin_launchd_coalition', 'darwin-launchd:ai.oktolabs.nexus-owned.123.'+'a'*16),
    }[platform]
    return ProcessLaunchIdentity(SessionKey('server', 'executor', 'session'), 'open', 2, 3,
                                  platform, containment, container, 'b'*32)


async def admitted(journal, launch):
    key = OperationKey(launch.key.server_id, launch.key.executor_id, launch.opening_operation_id)
    await journal.admit(key, 'intent', launch.key.session_id, claim_session=True,
        connection_generation=launch.connection_generation, session_owner_generation=launch.owner_generation)
    await journal.mark_possible_effect(key)
    return key


@pytest.mark.parametrize('platform', ['win32', 'linux', 'darwin'])
def test_identity_and_monotonic_fence_survive_reopen_without_releasing_capacity(tmp_path, platform):
    async def scenario():
        path, launch = tmp_path/'launch.db', identity(platform)
        journal = SQLiteJournal(path)
        try:
            key = await admitted(journal, launch)
            await journal.reserve_owned_slot(key, launch.key.session_id)
            prepared = await journal.prepare_process_launch(launch)
            assert prepared.state == 'PREPARED' and prepared.revision == 1
            assert await journal.get_process_birth(launch.key) is None
            assert await journal.prepare_process_launch(launch) == prepared
            fenced = await journal.transition_process_launch(launch, expected_revision=1, action='fence')
            assert fenced.state == 'FENCED' and fenced.revision == 2
            # Delayed retries cannot turn a sealed producer into a new launch.
            assert await journal.prepare_process_launch(launch) == fenced
            assert await journal.transition_process_launch(launch, expected_revision=1, action='fence') == fenced
        finally:
            await journal.aclose()
        journal = SQLiteJournal(path)
        try:
            assert await journal.get_process_launch(launch.key) == fenced
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_FENCED'):
                await journal.transition_process_launch(launch, expected_revision=2, action='claim')
            stopped = await journal.transition_process_launch(launch, expected_revision=2,
                action='stop', stop_proof='NEVER_CLAIMED')
            assert stopped.state == 'STOPPED' and stopped.revision == 3
            assert await journal.transition_process_launch(launch, expected_revision=2,
                action='stop', stop_proof='NEVER_CLAIMED') == stopped
            # Neither the record nor its stop proof settles effects or donates
            # capacity; the reconciler must do that under current authority.
            assert (await journal.get_receipt(key)).stage == 'SUBMISSION_STARTED'
            assert (await journal.owned_slot_page()).reservations
        finally:
            await journal.aclose()
    asyncio.run(scenario())


def test_concurrent_journal_connections_allow_exactly_one_claim(tmp_path):
    async def scenario():
        first, second = SQLiteJournal(tmp_path/'launch.db'), SQLiteJournal(tmp_path/'launch.db')
        launch = identity()
        try:
            await admitted(first, launch)
            await first.prepare_process_launch(launch)
            results = await asyncio.gather(*(journal.transition_process_launch(
                launch, expected_revision=1, action='claim')
                for journal in [first, second]*8), return_exceptions=True)
            assert sum(not isinstance(r, BaseException) for r in results) == 1
            assert all(not isinstance(r, BaseException) or
                isinstance(r, CoreError) and r.code == 'PROCESS_LAUNCH_REVISION_CONFLICT' for r in results)
            claimed = await second.get_process_launch(launch.key)
            assert claimed.state == 'CLAIMED' and claimed.revision == 2
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_ALREADY_CLAIMED'):
                await first.transition_process_launch(launch, expected_revision=2, action='claim')
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_PROOF_REQUIRED'):
                await first.transition_process_launch(launch, expected_revision=2,
                    action='stop', stop_proof='CONTAINER_STOPPED')
            fenced = await second.transition_process_launch(launch, expected_revision=2, action='fence')
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_PROOF_REQUIRED'):
                await first.transition_process_launch(launch, expected_revision=fenced.revision,
                    action='stop', stop_proof='NEVER_CLAIMED')
            stopped = await first.transition_process_launch(launch, expected_revision=fenced.revision,
                action='stop', stop_proof='CONTAINER_STOPPED')
            assert stopped.spawn_claimed and stopped.producer_fenced and stopped.state == 'STOPPED'
        finally:
            await first.aclose()
            await second.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('change', [
    {'opening_operation_id':'other'}, {'connection_generation':4}, {'owner_generation':4},
    {'container_id':'Global\\nexus-core-'+'c'*32}, {'producer_id':'c'*32},
])
def test_identity_cannot_be_replaced_or_used_to_fence_another_producer(tmp_path, change):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'launch.db'), identity()
        try:
            await admitted(journal, launch)
            original = await journal.prepare_process_launch(launch)
            other = replace(launch, **change)
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_CONFLICT'):
                await journal.prepare_process_launch(other)
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_CONFLICT'):
                await journal.transition_process_launch(other, expected_revision=1, action='fence')
            assert await journal.get_process_launch(launch.key) == original
        finally:
            await journal.aclose()
    asyncio.run(scenario())


def test_prepare_requires_original_admitted_claim_and_cannot_invent_prior_intent(tmp_path):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'launch.db'), identity()
        key = OperationKey('server', 'executor', 'open')
        try:
            with pytest.raises(CoreError, match='SESSION_UNKNOWN'):
                await journal.prepare_process_launch(launch)
            await journal.admit(key, 'intent', 'session', claim_session=True,
                connection_generation=2, session_owner_generation=3)
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_NOT_ADMITTED'):
                await journal.prepare_process_launch(launch)
            await journal.mark_possible_effect(key)
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_CONFLICT'):
                await journal.prepare_process_launch(replace(launch, owner_generation=9))
            await journal.record_process_birth(key, 'session', ProcessBirthEvidence(
                'win32', 1234, 'filetime:1234', 'windows_job', launch.container_id))
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_TOO_LATE'):
                await journal.prepare_process_launch(launch)
            assert await journal.get_process_launch(launch.key) is None
            assert await journal.get_process_launch(SessionKey('other', 'executor', 'session')) is None
        finally:
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('failure_at', ['insert', 'update'])
def test_transaction_failure_leaves_no_phantom_intent_or_fence(tmp_path, failure_at):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'launch.db'), identity()
        try:
            await admitted(journal, launch)
            if failure_at == 'update':
                await journal.prepare_process_launch(launch)
            journal._run_sync(lambda db: db.execute(f'''CREATE TRIGGER fail_launch BEFORE {failure_at.upper()} ON process_launches
                BEGIN SELECT RAISE(FAIL, 'injected launch persistence failure'); END'''))
            with pytest.raises(sqlite3.IntegrityError, match='injected'):
                if failure_at == 'insert':
                    await journal.prepare_process_launch(launch)
                else:
                    await journal.transition_process_launch(launch, expected_revision=1, action='fence')
            state = await journal.get_process_launch(launch.key)
            assert state is None if failure_at == 'insert' else state.state == 'PREPARED'
            journal._run_sync(lambda db: db.execute('DROP TRIGGER fail_launch'))
            await journal.prepare_process_launch(launch)
            assert (await journal.transition_process_launch(launch, expected_revision=1, action='fence')).state == 'FENCED'
        finally:
            await journal.aclose()
    asyncio.run(scenario())


def test_birth_requires_claimed_launch_and_exact_planned_container(tmp_path):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'launch.db'), identity()
        birth = ProcessBirthEvidence('win32',1234,'filetime:1234','windows_job',launch.container_id)
        try:
            key = await admitted(journal, launch)
            await journal.prepare_process_launch(launch)
            with pytest.raises(CoreError, match='PROCESS_BIRTH_CONFLICT'):
                await journal.record_process_birth(key, 'session', birth)
            await journal.transition_process_launch(launch, expected_revision=1, action='claim')
            with pytest.raises(CoreError, match='PROCESS_BIRTH_CONFLICT'):
                await journal.record_process_birth(key, 'session', replace(birth, container_id='Global\\nexus-core-'+'c'*32))
            recorded = await journal.record_process_birth(key, 'session', birth)
            await journal.transition_process_launch(launch, expected_revision=2, action='fence')
            assert await journal.record_process_birth(key, 'session', birth) == recorded
        finally:
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('change', [
    {'schema_version':2}, {'schema_version':True}, {'connection_generation':True},
    {'owner_generation':0}, {'container_id':'arbitrary-job'}, {'producer_id':'pid:1234'},
    {'platform':'remote'}, {'containment':'linux_guardian'},
])
def test_malformed_identity_rejected_before_storage(tmp_path, change):
    async def scenario():
        journal = SQLiteJournal(tmp_path/'launch.db')
        try:
            with pytest.raises(ValueError):
                await journal.prepare_process_launch(replace(identity(), **change))
            assert journal._run_sync(lambda db: db.execute('SELECT COUNT(*) FROM process_launches').fetchone())[0] == 0
        finally:
            await journal.aclose()
    asyncio.run(scenario())
