import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from nexus_connector_core import CoreError, LocalRuntimeCore, OperationKey, SessionKey
from nexus_connector_core.journal import SQLiteJournal


ROOT = Path(__file__).resolve().parents[1]
PEER = ROOT / "tests" / "fixtures" / "session_claim_peer.py"


def test_open_claim_is_durable_scoped_and_idempotent(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        first = OperationKey("server-a", "executor", "open-1")
        receipt, fresh = await journal.admit(first, "intent-1", "session",
                                             claim_session=True)
        assert fresh and receipt.session_id == "session"
        duplicate, fresh = await journal.admit(first, "intent-1", "session",
                                                claim_session=True)
        assert not fresh and duplicate == receipt
        journal.close()

        journal = SQLiteJournal(path)
        with pytest.raises(CoreError, match="SESSION_CONFLICT"):
            await journal.admit(OperationKey("server-a", "executor", "open-2"),
                                "intent-2", "session", claim_session=True)
        assert await journal.get_receipt(OperationKey("server-a", "executor",
                                                       "open-2")) is None
        _, fresh = await journal.admit(
            OperationKey("server-b", "executor", "open-2"),
            "intent-2", "session", claim_session=True)
        assert fresh
        journal.close()

    asyncio.run(run())


def test_open_generations_are_atomic_immutable_claim_history(tmp_path):
    async def run():
        path = tmp_path / "generations.db"
        journal = SQLiteJournal(path)
        key = OperationKey("srv", "exe", "open")
        receipt, fresh = await journal.admit(
            key, "intent", "session", claim_session=True,
            connection_generation=5, session_owner_generation=7)
        assert fresh
        page = await journal.claimed_sessions("srv", "exe")
        assert page.claims[0].opening_connection_generation == 5
        assert page.claims[0].opening_owner_generation == 7
        journal.close()

        reopened = SQLiteJournal(path)
        try:
            page = await reopened.claimed_sessions("srv", "exe")
            assert page.claims[0].opening_connection_generation == 5
            assert page.claims[0].opening_owner_generation == 7
            replay, fresh = await reopened.admit(
                key, "intent", "session", claim_session=True,
                connection_generation=5, session_owner_generation=7)
            assert not fresh and replay == receipt
            for mismatch in ({"connection_generation": 6,
                              "session_owner_generation": 7}, {}):
                with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
                    await reopened.admit(key, "intent", "session",
                                         claim_session=True, **mismatch)
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await reopened.admit(OperationKey("srv", "exe", "other-open"),
                                     "other", "session", claim_session=True,
                                     connection_generation=8,
                                     session_owner_generation=9)
            assert (await reopened.claimed_sessions("srv", "exe")).claims == page.claims
        finally:
            reopened.close()

    asyncio.run(run())


@pytest.mark.parametrize("generations", [
    {"connection_generation": 1},
    {"session_owner_generation": 1},
    {"connection_generation": True, "session_owner_generation": 1},
    {"connection_generation": 1, "session_owner_generation": 0},
    {"connection_generation": 2**63, "session_owner_generation": 1},
])
def test_invalid_open_generations_fail_before_journal_write(tmp_path, generations):
    async def run():
        journal = SQLiteJournal(tmp_path / "invalid-generations.db")
        try:
            with pytest.raises(ValueError):
                await journal.admit(OperationKey("srv", "exe", "open"),
                                    "intent", "session", claim_session=True,
                                    **generations)
            assert (await journal.claimed_sessions("srv", "exe")).claims == ()
            assert await journal.get_receipt(
                OperationKey("srv", "exe", "open")) is None
        finally:
            journal.close()

    asyncio.run(run())


def test_two_journal_connections_cannot_claim_same_session(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        first, second = SQLiteJournal(path), SQLiteJournal(path)
        results = await asyncio.gather(
            first.admit(OperationKey("srv", "exe", "open-a"), "a", "session",
                        claim_session=True),
            second.admit(OperationKey("srv", "exe", "open-b"), "b", "session",
                         claim_session=True),
            return_exceptions=True)
        assert sum(isinstance(item, tuple) for item in results) == 1
        assert sum(isinstance(item, CoreError) and item.code == "SESSION_CONFLICT"
                   for item in results) == 1
        first.close()
        second.close()

    asyncio.run(run())


def test_two_processes_cannot_claim_same_session(tmp_path):
    path = tmp_path / "journal.db"
    SQLiteJournal(path).close()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    peers = []
    try:
        for operation_id in ("open-a", "open-b"):
            peers.append(subprocess.Popen(
                [sys.executable, str(PEER), str(path), operation_id],
                cwd=ROOT, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for peer in peers:
            assert peer.stdin is not None
            peer.stdin.write(b"x")
            peer.stdin.close()
            peer.stdin = None
        outcomes = []
        for peer in peers:
            stdout, stderr = peer.communicate(timeout=30)
            assert peer.returncode == 0, stderr.decode(errors="replace")
            outcomes.append(json.loads(stdout))
        assert sorted(item["result"] for item in outcomes) == ["admitted", "conflict"]
        journal = SQLiteJournal(path)
        assert journal._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM session_claims").fetchone())[0] == 1
        assert journal._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM operations_v2").fetchone())[0] == 1
        winner = next(item["operation_id"] for item in outcomes
                      if item["result"] == "admitted")
        claim = asyncio.run(journal.claimed_sessions("srv", "exe")).claims[0]
        generation = 5 if winner == "open-a" else 6
        assert claim.opening_operation_id == winner
        assert claim.opening_connection_generation == generation
        assert claim.opening_owner_generation == generation + 2
        journal.close()
    finally:
        for peer in peers:
            if peer.poll() is None:
                peer.kill()
                peer.wait(timeout=5)


def test_existing_journal_session_history_is_backfilled_as_claim(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        await journal.admit(OperationKey("srv", "exe", "old-operation"),
                            "old", "session")
        journal.close()
        journal = SQLiteJournal(path)
        with pytest.raises(CoreError, match="SESSION_CONFLICT"):
            await journal.admit(OperationKey("srv", "exe", "new-open"),
                                "new", "session", claim_session=True)
        claim = (await journal.claimed_sessions("srv", "exe")).claims[0]
        assert claim.opening_connection_generation is None
        assert claim.opening_owner_generation is None
        journal.close()

    asyncio.run(run())


def test_failed_operation_insert_rolls_back_session_claim(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        journal._run_sync(lambda db: db.execute("""CREATE TRIGGER fail_open_operation
            BEFORE INSERT ON operations_v2 BEGIN
            SELECT RAISE(ABORT, 'injected operation insert failure');
            END"""))
        key = OperationKey("srv", "exe", "open-1")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            await journal.admit(key, "intent", "session", claim_session=True,
                                connection_generation=5,
                                session_owner_generation=7)
        assert journal._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM session_claims").fetchone())[0] == 0
        assert journal._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM session_open_generations").fetchone())[0] == 0
        journal._run_sync(lambda db: db.execute("DROP TRIGGER fail_open_operation"))
        _, fresh = await journal.admit(key, "intent", "session",
                                       claim_session=True,
                                       connection_generation=5,
                                       session_owner_generation=7)
        assert fresh
        journal.close()

    asyncio.run(run())


def test_claim_inventory_pages_stable_restart_snapshot_and_namespace(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        for index in range(3):
            await journal.admit(OperationKey("srv", "exe", f"open-{index}"),
                                f"intent-{index}", f"session-{index}",
                                claim_session=True)
        await journal.admit(OperationKey("other", "exe", "other-open"),
                            "other", "session-0", claim_session=True)
        first = await journal.claimed_sessions("srv", "exe", limit=2)
        assert [claim.key for claim in first.claims] == [
            SessionKey("srv", "exe", "session-0"),
            SessionKey("srv", "exe", "session-1")]
        assert first.next_after_rowid is not None
        assert first.claims[0].opening_operation_id == "open-0"
        await journal.admit(OperationKey("srv", "exe", "late-open"),
                            "late", "late-session", claim_session=True)
        journal.close()

        journal = SQLiteJournal(path)
        second = await journal.claimed_sessions(
            "srv", "exe", after_rowid=first.next_after_rowid,
            high_water_rowid=first.high_water_rowid, limit=2)
        assert [claim.key.session_id for claim in second.claims] == ["session-2"]
        assert second.next_after_rowid is None
        fresh = await journal.claimed_sessions("srv", "exe", limit=4)
        assert {claim.key.session_id for claim in fresh.claims} == {
            "session-0", "session-1", "session-2", "late-session"}
        assert fresh.next_after_rowid is None
        assert [claim.key.server_id for claim in (
            await journal.claimed_sessions("other", "exe")).claims] == ["other"]
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("kwargs", [
    {"limit": True}, {"limit": 0}, {"limit": 4097},
    {"after_rowid": -1}, {"after_rowid": 1.5},
    {"high_water_rowid": True}, {"high_water_rowid": -1},
    {"after_rowid": 2, "high_water_rowid": 1},
])
def test_claim_inventory_rejects_invalid_page_parameters(tmp_path, kwargs):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        with pytest.raises(ValueError):
            await journal.claimed_sessions("srv", "exe", **kwargs)
        journal.close()

    asyncio.run(run())


def test_runtime_claim_inventory_fences_invalid_host_requests_before_port():
    class HostJournal:
        called = False

        async def claimed_sessions(self, *args, **kwargs):
            self.called = True
            raise AssertionError("invalid request reached host journal")

    async def run():
        journal = HostJournal()
        runtime = LocalRuntimeCore(journal, object(), candidates={},
                                   workspace_roots={})
        for server, executor, kwargs in (
                ("", "exe", {}), ("srv", "", {}),
                ("srv", "exe", {"limit": True}),
                ("srv", "exe", {"high_water_rowid": -1})):
            with pytest.raises(ValueError):
                await runtime.claimed_sessions(server, executor, **kwargs)
        assert not journal.called

    asyncio.run(run())
