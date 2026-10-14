"""T24: lease refusal admission and terminal fact survive exact commit cuts."""
import sqlite3
import pytest

from nexus_connector_core import CoreError, OperationKey, SessionKey, persist_r4_lease_refusal
from nexus_connector_core.journal import open_journal
from test_r4_operation_refusal import refusal


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['rollback', 'lost_reply'])
@pytest.mark.parametrize('stage', ['RECEIVED_DURABLE', 'FAILED'])
async def test_refusal_commit_cut_recovers_original_fact_without_native_claim(tmp_path, monkeypatch, boundary, stage):
    frame, proof = refusal()
    key = OperationKey(frame['server_id'], frame['executor_id'], frame['operation_id'])
    path = tmp_path / 'refusal.sqlite3'
    journal = await open_journal(path)
    run, fired = journal._run, []

    class CutConnection:
        def __init__(self, db):
            self.db = db

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, sql, *args):
            if sql.strip().upper() == 'COMMIT' and not fired:
                row = self.db.execute('SELECT stage FROM operations_v2 WHERE server_id=? AND executor_id=? AND operation_id=?',
                                      (key.server_id, key.executor_id, key.operation_id)).fetchone()
                if row is not None and row[0] == stage:
                    fired.append(stage)
                    if boundary == 'lost_reply':
                        self.db.execute(sql, *args)
                    raise OSError('Refusal commit cut')
            return self.db.execute(sql, *args)

    async def cut_run(work, **kwargs):
        return await run(lambda db: work(CutConnection(db)), **kwargs)

    monkeypatch.setattr(journal, '_run', cut_run)
    try:
        with pytest.raises((OSError, CoreError)):
            await persist_r4_lease_refusal(journal, proof)
        assert fired == [stage]
    finally:
        await journal.aclose()
    rebuilt = await open_journal(path)
    try:
        observed = await rebuilt.get_receipt(key)
        expected = stage if boundary == 'lost_reply' else (None if stage == 'RECEIVED_DURABLE' else 'RECEIVED_DURABLE')
        assert (observed.stage if observed is not None else None) == expected
        if observed is not None:
            assert observed.intent_hash == proof['binding']['core_intent_hash']
            assert not observed.possible_effect and observed.retry_safe and observed.native_id is None
        final = await persist_r4_lease_refusal(rebuilt, proof)
        assert final.stage == 'FAILED' and final.error_code == 'LEASE_REVALIDATION_REQUIRED'
        assert not final.possible_effect and final.retry_safe and final.native_id is None
        assert await persist_r4_lease_refusal(rebuilt, proof) == final
        assert await rebuilt.get_session_claim(SessionKey(key.server_id, key.executor_id, frame['session_id'])) is None
        assert not (await rebuilt.owned_slot_page()).reservations
        with pytest.raises(CoreError, match='OPERATION_CONFLICT'):
            await rebuilt.admit(key, 'different-native-intent', frame['session_id'], effect_imminent=True)
        assert await rebuilt.get_receipt(key) == final
    finally:
        await rebuilt.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', [None, 'rollback', 'lost_reply'])
async def test_legacy_claim_backfill_is_atomic_and_runs_only_once(tmp_path, monkeypatch, boundary):
    path = tmp_path / 'legacy.sqlite3'
    original = OperationKey('server', 'executor', 'legacy-open')
    journal = await open_journal(path)
    await journal.admit(original, 'legacy-intent', 'legacy-session', effect_imminent=True)
    await journal.aclose()
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE session_claims')
    fired = []
    if boundary is not None:
        connect = sqlite3.connect

        class MigrationCut(sqlite3.Connection):
            creating_claims = False

            def execute(self, sql, *args):
                normalized = ' '.join(sql.upper().split())
                if normalized.startswith('CREATE TABLE SESSION_CLAIMS'):
                    self.creating_claims = True
                if normalized == 'COMMIT' and self.creating_claims and not fired:
                    fired.append(boundary)
                    if boundary == 'lost_reply':
                        super().execute(sql, *args)
                    raise OSError('Legacy claim migration cut')
                return super().execute(sql, *args)

        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, 'connect', lambda *a, **kw: connect(*a, **dict(kw, factory=MigrationCut)))
            with pytest.raises((OSError, CoreError)):
                await open_journal(path)
        assert fired == [boundary]
        with sqlite3.connect(path) as conn:
            present = conn.execute("SELECT 1 FROM sqlite_master WHERE name='session_claims'").fetchone()
            assert bool(present) is (boundary == 'lost_reply')
    migrated = await open_journal(path)
    legacy_key = SessionKey(original.server_id, original.executor_id, 'legacy-session')
    try:
        claim = await migrated.get_session_claim(legacy_key)
        assert claim is not None and claim.opening_operation_id == original.operation_id
        # New operations without claim_session are authoritative omissions.
        await migrated.admit(OperationKey('server', 'executor', 'refusal'), 'no-effect', 'refused-session')
        assert await migrated.get_session_claim(SessionKey('server', 'executor', 'refused-session')) is None
    finally:
        await migrated.aclose()
    reopened = await open_journal(path)
    try:
        assert await reopened.get_session_claim(legacy_key) == claim
        assert await reopened.get_session_claim(SessionKey('server', 'executor', 'refused-session')) is None
    finally:
        await reopened.aclose()
