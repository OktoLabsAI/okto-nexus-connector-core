"""Interrupted launch proof settles its opening, never replays or releases it."""
import asyncio
from dataclasses import replace
import sqlite3

import pytest

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import CoreError, OperationKey
from nexus_connector_core.native.process.launch_recovery import recover_process_launch
from nexus_connector_core.process_launch_control import ProcessLaunchController
from nexus_connector_core.native.process.launch_exclusion import HostLaunchExclusion
from test_process_launch_storage import identity


async def prepare(journal, *, marked):
    launch = identity()
    key = OperationKey('server', 'executor', 'open')
    await journal.admit(key, 'intent', 'session', claim_session=True,
        connection_generation=2, session_owner_generation=3, process_launch_identity=launch)
    if marked:
        await journal.mark_possible_effect(key)
        await journal.reserve_owned_slot(key, 'session')
    return launch, key


@pytest.mark.parametrize('marked', [False, True])
def test_settlement_is_durable_and_preserves_possible_effect(tmp_path, marked):
    async def scenario():
        path = tmp_path/'journal.db'
        journal = SQLiteJournal(path)
        try:
            launch, key = await prepare(journal, marked=marked)
            result = await recover_process_launch(journal, launch.key,
                connection_generation=3, validate_authority=lambda: None)
            assert result.record.stop_proof == 'NEVER_CLAIMED'
            receipt = await journal.get_receipt(key)
            assert receipt.stage == 'FAILED' and receipt.error_code == 'PROCESS_LAUNCH_FENCED'
            assert receipt.possible_effect is marked and receipt.retry_safe is not marked
            assert bool((await journal.owned_slot_page()).reservations) is marked
            assert await journal.get_process_birth(launch.key) is None
        finally:
            await journal.aclose()
        journal = SQLiteJournal(path)
        try:
            assert await journal.settle_unclaimed_process_launch(launch) == receipt
            assert await journal.get_receipt(key) == receipt
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_FENCED'):
                await journal.transition_process_launch(launch, expected_revision=3, action='claim')
        finally:
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('fault', ['unfenced', 'fenced_only', 'claimed_stopped', 'wrong_identity'])
def test_missing_or_unrelated_proof_cannot_change_operation(tmp_path, fault):
    async def scenario():
        journal = SQLiteJournal(tmp_path/'journal.db')
        try:
            launch, key = await prepare(journal, marked=True)
            old = await journal.get_receipt(key)
            if fault == 'fenced_only':
                await journal.transition_process_launch(launch, expected_revision=1, action='fence')
            elif fault in ('claimed_stopped', 'wrong_identity'):
                if fault == 'claimed_stopped':
                    await journal.transition_process_launch(launch, expected_revision=1, action='claim')
                await ProcessLaunchController(journal, HostLaunchExclusion()).recover(launch,
                    validate_authority=lambda: None, stop_container=lambda _: 'STOPPED')
                if fault == 'wrong_identity':
                    launch = replace(launch, opening_operation_id='foreign')
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_PROOF_REQUIRED'):
                await journal.settle_unclaimed_process_launch(launch)
            assert await journal.get_receipt(key) == old
        finally:
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('fault', ['same_generation', 'old_generation', 'authority_revoked'])
def test_replacement_must_have_current_authority_before_fencing(tmp_path, fault):
    async def scenario():
        journal = SQLiteJournal(tmp_path/'journal.db')
        try:
            launch, key = await prepare(journal, marked=True)
            original = await journal.get_process_launch(launch.key)
            def authority():
                if fault == 'authority_revoked':
                    raise CoreError('LEASE_REVOKED', 'test')
            with pytest.raises(CoreError):
                await recover_process_launch(journal, launch.key,
                    connection_generation={'same_generation':2, 'old_generation':1}.get(fault, 3),
                    validate_authority=authority)
            assert await journal.get_process_launch(launch.key) == original
            assert (await journal.get_receipt(key)).stage == 'SUBMISSION_STARTED'
        finally:
            await journal.aclose()
    asyncio.run(scenario())


def test_failed_settlement_rolls_back_and_retries_from_retained_proof(tmp_path):
    async def scenario():
        journal = SQLiteJournal(tmp_path/'journal.db')
        try:
            launch, key = await prepare(journal, marked=True)
            await ProcessLaunchController(journal, HostLaunchExclusion()).recover(launch,
                validate_authority=lambda: None, stop_container=lambda _: pytest.fail('No spawn was claimed'))
            old = await journal.get_receipt(key)
            journal._run_sync(lambda db: db.execute('''CREATE TRIGGER fail_settle BEFORE UPDATE ON operations_v2
                BEGIN SELECT RAISE(FAIL, 'injected settlement failure'); END'''))
            with pytest.raises(sqlite3.IntegrityError, match='injected'):
                await journal.settle_unclaimed_process_launch(launch)
            assert await journal.get_receipt(key) == old
            assert (await journal.get_process_launch(launch.key)).stop_proof == 'NEVER_CLAIMED'
            journal._run_sync(lambda db: db.execute('DROP TRIGGER fail_settle'))
            settled = await journal.settle_unclaimed_process_launch(launch)
            assert settled.stage == 'FAILED' and settled.possible_effect
        finally:
            await journal.aclose()
    asyncio.run(scenario())
