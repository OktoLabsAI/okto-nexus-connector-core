import asyncio
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, OperationKey, SQLiteOwnedSlotLedger
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


async def claimed_open(journal, session_id):
    key = OperationKey("srv", "exe", f"open-{session_id}")
    await journal.admit(key, f"intent-{session_id}", session_id,
                        claim_session=True, effect_imminent=True)
    return key


def test_shared_journal_slot_budget_survives_reopen_and_requires_explicit_release(tmp_path):
    async def run():
        path = tmp_path / "slots.db"
        limits = replace(JournalLimits(), max_owned_slots=2)
        journal = SQLiteJournal(path, limits=limits)
        first = await claimed_open(journal, "one")
        second = await claimed_open(journal, "two")
        third = await claimed_open(journal, "three")
        await journal.reserve_owned_slot(first, "one")
        await journal.reserve_owned_slot(second, "two")
        page = await journal.owned_slot_page(limit=1)
        assert [item.key.session_id for item in page.reservations] == ["one"]
        assert page.next_after_rowid is not None
        final = await journal.owned_slot_page(
            after_rowid=page.next_after_rowid,
            high_water_rowid=page.high_water_rowid, limit=1)
        assert [item.key.session_id for item in final.reservations] == ["two"]
        with pytest.raises(CoreError, match="CAPACITY_EXCEEDED") as caught:
            await journal.reserve_owned_slot(third, "three")
        assert caught.value.retry_safe is True
        journal.close()

        reopened = SQLiteJournal(path, limits=limits)
        try:
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
                await reopened.reserve_owned_slot(third, "three")
            page = await reopened.owned_slot_page()
            assert {item.key.session_id for item in page.reservations} == {
                "one", "two"}
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await reopened.release_owned_slot(third, "one")
            assert await reopened.release_owned_slot(first, "one") is True
            assert await reopened.release_owned_slot(first, "one") is False
            assert {item.key.session_id for item in
                    (await reopened.owned_slot_page()).reservations} == {"two"}
            await reopened.reserve_owned_slot(third, "three")
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await reopened.reserve_owned_slot(first, "one")
            assert reopened._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 2
        finally:
            reopened.close()

    asyncio.run(run())


def test_two_journal_connections_cannot_exceed_last_shared_slot(tmp_path):
    async def run():
        path = tmp_path / "race.db"
        limits = replace(JournalLimits(), max_owned_slots=1)
        first, second = (SQLiteJournal(path, limits=limits) for _ in range(2))
        try:
            key_a = await claimed_open(first, "a")
            key_b = await claimed_open(second, "b")
            results = await asyncio.gather(
                first.reserve_owned_slot(key_a, "a"),
                second.reserve_owned_slot(key_b, "b"),
                return_exceptions=True)
            assert sum(result is None for result in results) == 1
            assert sum(isinstance(result, CoreError) and
                       result.code == "CAPACITY_EXCEEDED"
                       for result in results) == 1
            assert first._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 1
        finally:
            first.close()
            second.close()

    asyncio.run(run())


def test_slot_policy_mismatch_and_insert_failure_fail_closed(tmp_path):
    async def run():
        path = tmp_path / "policy.db"
        two = replace(JournalLimits(), max_owned_slots=2)
        first = SQLiteJournal(path, limits=two)
        key = await claimed_open(first, "one")
        first._run_sync(lambda db: db.execute("""CREATE TRIGGER reject_slot BEFORE INSERT
            ON owned_slot_reservations BEGIN
            SELECT RAISE(ABORT, 'injected slot failure'); END"""))
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            await first.reserve_owned_slot(key, "one")
        assert first._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM owned_slot_policy").fetchone())[0] == 0
        first._run_sync(lambda db: db.execute("DROP TRIGGER reject_slot"))
        await first.reserve_owned_slot(key, "one")
        different = SQLiteJournal(
            path, limits=replace(JournalLimits(), max_owned_slots=3))
        try:
            other = await claimed_open(different, "other")
            with pytest.raises(CoreError, match="PROFILE_DRIFT"):
                await different.reserve_owned_slot(other, "other")
            with pytest.raises(CoreError, match="PROFILE_DRIFT"):
                await different.release_owned_slot(key, "one")
            with pytest.raises(CoreError, match="PROFILE_DRIFT"):
                await different.owned_slot_page()
            assert first._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 1
        finally:
            different.close()
            first.close()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["journal", "installation"])
def test_three_crashing_processes_contend_for_two_shared_slots(tmp_path, mode):
    path = tmp_path / "multiprocess-slots.db"
    source = Path(__file__).resolve().parents[1]
    peer = source / "tests" / "fixtures" / "owned_slot_peer.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(source / "src"), env.get("PYTHONPATH", ""))
        if item)
    processes = []
    ready = queue.Queue()
    try:
        for contender in ("a", "b", "c"):
            process = subprocess.Popen(
                [sys.executable, str(peer), str(path), contender, mode],
                cwd=source, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append(process)
            threading.Thread(
                target=lambda p=process: ready.put((p, p.stdout.readline())),
                daemon=True).start()
        for _ in processes:
            process, line = ready.get(timeout=15)
            assert line == "ready\n", (
                process.stderr.read() if process.poll() is not None else line)
        for process in processes:
            process.stdin.write("x")
            process.stdin.close()
            process.stdin = None
        outcomes = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 91, stderr
            outcomes.append(json.loads(stdout)["result"])
        assert sorted(outcomes) == ["CAPACITY_EXCEEDED", "reserved", "reserved"]
        journal = (SQLiteJournal(
            path, limits=replace(JournalLimits(), max_owned_slots=2))
                   if mode == "journal" else
                   SQLiteOwnedSlotLedger(path, max_slots=2))
        try:
            page = asyncio.run(journal.owned_slot_page())
            assert len(page.reservations) == 2
            assert {item.key.session_id for item in page.reservations} == {
                f"session-{contender}"
                for contender, result in zip(("a", "b", "c"), outcomes)
                if result == "reserved"}
        finally:
            journal.close()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe:
                    pipe.close()
