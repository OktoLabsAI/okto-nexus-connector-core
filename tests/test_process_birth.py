"""OS birth evidence is scoped to Core-owned process containers."""

import asyncio
import subprocess
import sys
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import ProcessBirthEvidence, SessionKey
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import CoreError, OperationKey
from nexus_connector_core.native.process import (
    observe_recorded_process_birth, snapshot_owned_process_birth,
    spawn_owned_process,
)


def test_plain_subprocess_cannot_claim_core_birth_identity():
    process = subprocess.Popen(
        [sys.executable, "-c", "pass"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with pytest.raises(TypeError):
            snapshot_owned_process_birth(process)
    finally:
        process.communicate(timeout=10)


@pytest.mark.skipif(sys.platform not in {"win32", "linux", "darwin"},
                    reason="owned process backend unqualified")
def test_owned_process_birth_token_is_stable_for_one_handle_and_distinct_between_births():
    def born():
        process = spawn_owned_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=str(Path.cwd()), env=dict(os.environ), text=True)
        try:
            first = snapshot_owned_process_birth(process)
            assert snapshot_owned_process_birth(process) == first
            assert first.pid == process.pid
            assert first.platform == sys.platform
            assert first.containment in {"windows_job", "linux_guardian", "darwin_launchd_coalition"}
            assert observe_recorded_process_birth(first) == "MATCHING_LIVE"
            assert observe_recorded_process_birth(replace(
                first, birth_token=first.birth_token + "-other")) == "DIFFERENT_BIRTH"
            return first
        finally:
            process.kill()
            process.wait(timeout=10)

    first = born()
    second = born()
    assert (first.pid, first.birth_token) != (second.pid, second.birth_token)
    assert observe_recorded_process_birth(second) in {
        "NOT_RUNNING", "NOT_OBSERVED"}


def test_foreign_platform_birth_is_not_observed_as_local():
    foreign = "win32" if sys.platform != "win32" else "linux"
    containment = "windows_job" if foreign == "win32" else "linux_guardian"
    assert observe_recorded_process_birth(ProcessBirthEvidence(
        foreign, 1234, "foreign", containment)) == "UNKNOWN"


@pytest.mark.parametrize('platform,containment', [
    ('linux', 'linux_guardian'), ('darwin', 'darwin_launchd_coalition'), ('win32', 'windows_job')])
def test_birth_record_is_immutable_scoped_and_survives_reopen(tmp_path, platform, containment):
    async def run():
        path = tmp_path / "birth.db"
        key = OperationKey("server", "executor", "open")
        session = SessionKey("server", "executor", "session")
        evidence = ProcessBirthEvidence(platform, 1234,
                                        "boot-start:boot-1:123", containment)
        journal = SQLiteJournal(path)
        await journal.admit(key, "intent", session.session_id,
                            claim_session=True)
        await journal.mark_possible_effect(key)
        expected = await journal.record_process_birth(
            key, session.session_id, evidence)
        assert expected.key == session
        assert await journal.record_process_birth(
            key, session.session_id, evidence) == expected
        with pytest.raises(CoreError, match="PROCESS_BIRTH_CONFLICT"):
            await journal.record_process_birth(key, session.session_id,
                ProcessBirthEvidence(platform, 1235,
                                     "boot-start:boot-1:124", containment))
        with pytest.raises(CoreError, match="SESSION_CONFLICT"):
            await journal.record_process_birth(
                OperationKey("server", "executor", "other"),
                session.session_id, evidence)
        assert await journal.get_process_birth(
            SessionKey("other-server", "executor", "session")) is None
        journal.close()

        journal = SQLiteJournal(path)
        assert await journal.get_process_birth(session) == expected
        journal.close()

    asyncio.run(run())


def test_birth_record_rejects_unclaimed_or_prewrite_session(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "birth.db")
        key = OperationKey("server", "executor", "open")
        evidence = ProcessBirthEvidence("win32", 1234,
                                        "filetime:12345678", "windows_job")
        with pytest.raises(CoreError, match="SESSION_UNKNOWN"):
            await journal.record_process_birth(key, "session", evidence)
        await journal.admit(key, "intent", "session", claim_session=True)
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            await journal.record_process_birth(key, "session", evidence)
        assert await journal.get_process_birth(
            SessionKey("server", "executor", "session")) is None
        journal.close()

    asyncio.run(run())


def test_birth_insert_failure_rolls_back_without_phantom_record(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "birth.db")
        key = OperationKey("server", "executor", "open")
        session = SessionKey("server", "executor", "session")
        evidence = ProcessBirthEvidence("linux", 1234,
                                        "boot-start:boot-1:123", "linux_guardian")
        await journal.admit(key, "intent", session.session_id,
                            claim_session=True)
        await journal.mark_possible_effect(key)
        journal._run_sync(lambda db: db.execute("""CREATE TRIGGER fail_birth BEFORE INSERT ON process_births
                            BEGIN SELECT RAISE(FAIL, 'injected birth failure'); END"""))
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            await journal.record_process_birth(key, session.session_id, evidence)
        assert await journal.get_process_birth(session) is None
        journal._run_sync(lambda db: db.execute("DROP TRIGGER fail_birth"))
        assert (await journal.record_process_birth(
            key, session.session_id, evidence)).evidence == evidence
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("evidence", [
    ProcessBirthEvidence([], 1234, "token", "linux_guardian"),
    ProcessBirthEvidence("linux", 1234, "token", []),
    ProcessBirthEvidence("linux", True, "token", "linux_guardian"),
    ProcessBirthEvidence("linux", 1234, "", "linux_guardian"),
    ProcessBirthEvidence("linux", 1234, "token", "windows_job"),
    ProcessBirthEvidence("darwin", 1234, "token", "linux_guardian"),
    ProcessBirthEvidence("linux", 1234, "token", "darwin_launchd_coalition"),
])
def test_birth_record_rejects_malformed_evidence_before_storage(tmp_path, evidence):
    async def run():
        journal = SQLiteJournal(tmp_path / "birth.db")
        with pytest.raises(ValueError):
            await journal.record_process_birth(
                OperationKey("server", "executor", "open"),
                "session", evidence)
        assert journal._run_sync(lambda db: db.execute("SELECT COUNT(*) FROM process_births").fetchone())[0] == 0
        journal.close()

    asyncio.run(run())
