"""Crash frontier: the claim and launch intent are one admission transaction."""
import asyncio
from dataclasses import replace
import sqlite3
import time

import pytest

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel
from nexus_connector_core.models import CoreError, ExecutionContext, Operation, OperationKey
from test_process_launch_storage import identity


def context():
    return ExecutionContext('server', 'executor', 'binding', 'agent', 'workspace',
        1, 1, 2, time.monotonic()+60, frozenset({'runtime.open'}), session_owner_generation=3)


async def admit(journal, launch):
    return await journal.admit(OperationKey('server', 'executor', 'open'), 'intent', 'session',
        claim_session=True, connection_generation=2, session_owner_generation=3,
        process_launch_identity=launch)


def test_claim_and_intent_survive_restart_before_effect_marker(tmp_path):
    async def scenario():
        path, launch = tmp_path/'journal.db', identity()
        journal = SQLiteJournal(path)
        try:
            receipt, fresh = await admit(journal, launch)
            assert fresh and not receipt.possible_effect
        finally:
            await journal.aclose()
        journal = SQLiteJournal(path)
        try:
            assert (await journal.get_session_claim(launch.key)).opening_operation_id == 'open'
            record = await journal.get_process_launch(launch.key)
            assert record.identity == launch and record.state == 'PREPARED'
            assert await journal.get_process_birth(launch.key) is None
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_NOT_ADMITTED'):
                await journal.transition_process_launch(launch, expected_revision=1, action='claim')
            # A duplicate caller may have allocated fresh tentative identities;
            # it gets the original receipt, never another permission to spawn.
            duplicate, fresh = await admit(journal, replace(launch, producer_id='c'*32))
            assert not fresh and duplicate == receipt
            assert await journal.get_process_launch(launch.key) == record
        finally:
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('table', ['operations_v2', 'process_launches', 'operation_usage'])
def test_any_admission_failure_rolls_back_claim_intent_and_usage(tmp_path, table):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        try:
            action = 'UPDATE' if table == 'operation_usage' else 'INSERT'
            journal._run_sync(lambda db: db.execute(f'''CREATE TRIGGER fail_admission BEFORE {action} ON {table}
                BEGIN SELECT RAISE(FAIL, 'injected admission failure'); END'''))
            with pytest.raises(sqlite3.IntegrityError, match='injected'):
                await admit(journal, launch)
            assert await journal.get_process_launch(launch.key) is None
            assert await journal.get_session_claim(launch.key) is None
            assert await journal.get_receipt(OperationKey('server', 'executor', 'open')) is None
            assert journal._run_sync(lambda db: db.execute(
                'SELECT operation_rows FROM operation_usage').fetchone()[0]) == 0
            journal._run_sync(lambda db: db.execute('DROP TRIGGER fail_admission'))
            assert (await admit(journal, launch))[1]
        finally:
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('change', [
    {'opening_operation_id': 'other'}, {'owner_generation': 9}, {'connection_generation': 9},
])
def test_wrong_identity_refused_before_claim(tmp_path, change):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        try:
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_CONFLICT'):
                await admit(journal, replace(launch, **change))
            assert await journal.get_session_claim(launch.key) is None
        finally:
            await journal.aclose()
    asyncio.run(scenario())


def test_kernel_commits_intent_before_marker_and_effect_and_deduplicates(tmp_path):
    async def scenario():
        journal, launch = SQLiteJournal(tmp_path/'journal.db'), identity()
        marked, called = [], []
        original_marker = journal.mark_possible_effect
        async def mark(key):
            record = await journal.get_process_launch(launch.key)
            assert record is not None and record.identity == launch
            assert (await journal.get_receipt(key)).stage == 'RECEIVED_DURABLE'
            marked.append(key)
            return await original_marker(key)
        journal.mark_possible_effect = mark
        kernel = OperationKernel(journal)
        operation = Operation('open', 'session', 'runtime.open', {})
        async def effect():
            called.append(True)
            assert (await journal.get_process_launch(launch.key)).state == 'PREPARED'
            return 'native'
        try:
            first = await kernel.execute(operation, context(), effect, process_launch_identity=launch)
            again = await kernel.execute(operation, context(), effect,
                process_launch_identity=replace(launch, producer_id='c'*32))
            assert first == again and len(marked) == len(called) == 1
        finally:
            await journal.aclose()
    asyncio.run(scenario())
