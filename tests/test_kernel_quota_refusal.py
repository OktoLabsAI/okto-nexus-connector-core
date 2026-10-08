"""Quota refusals retain no-effect receipts without productive admission."""
import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, Operation, OperationKey
from nexus_connector_core.journal import JournalLimits, SQLiteJournal
from nexus_connector_core.kernel import OperationKernel
from test_kernel import context


@pytest.mark.parametrize('action', ['turn.submit', 'turn.steer'])
def test_quota_refusal_survives_restart_and_never_replays(tmp_path, action):
    async def run():
        path = tmp_path / 'quota.db'
        limits = JournalLimits(max_operation_rows=3, reserved_operation_rows=2)
        journal = SQLiteJournal(path, limits=limits)
        auth = replace(context(), allowed_actions=frozenset({action}))
        operation = Operation('refused', 'session', action, {'text': 'No native effect'})
        calls = []
        async def effect():
            calls.append('native')
        await journal.admit(OperationKey('srv', 'exe', 'existing'), 'existing', 'session')
        first = await OperationKernel(journal).execute(operation, auth, effect)
        assert first.stage == 'FAILED' and first.error_code == 'JOURNAL_FULL'
        assert first.retry_safe and not first.possible_effect and calls == []
        await journal.aclose()
        journal = SQLiteJournal(path)
        try:
            kernel = OperationKernel(journal)
            assert await kernel.execute(operation, auth, effect) == first
            assert calls == []
            following = await kernel.execute(replace(operation, operation_id='new'), auth, effect)
            assert following.stage == 'SUBMITTED' and calls == ['native']
        finally:
            await journal.aclose()
    asyncio.run(run())


def test_exhausted_critical_reserve_still_refuses_without_invented_receipt(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / 'full.db', limits=JournalLimits(
            max_operation_rows=2, reserved_operation_rows=1))
        try:
            for name in ('one', 'two'):
                await journal.admit(OperationKey('srv', 'exe', name), name, 'session', critical=True)
            async def forbidden():
                pytest.fail('A quota refusal must never call the native effect')
            with pytest.raises(CoreError, match='JOURNAL_FULL'):
                await OperationKernel(journal).execute(Operation('refused', 'session', 'turn.submit'), context(), forbidden)
            assert await journal.get_receipt(OperationKey('srv', 'exe', 'refused')) is None
        finally:
            await journal.aclose()
    asyncio.run(run())
