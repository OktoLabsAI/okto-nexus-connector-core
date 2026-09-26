import asyncio
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from nexus_connector_core import CoreError, OperationKey
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


ROOT = Path(__file__).resolve().parents[1]
PEER = ROOT / "tests" / "fixtures" / "journal_fairness_peer.py"


def run_peers(path, limits, specs, attempts, *, critical=False):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    peers = []
    try:
        for server, session, prefix in specs:
            peers.append(subprocess.Popen(
                [sys.executable, str(PEER), str(path), server, session, prefix,
                 json.dumps(asdict(limits)), str(attempts),
                 "critical" if critical else "normal"],
                cwd=ROOT, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for peer in peers:
            assert peer.stdin is not None
            peer.stdin.write(b"x")
            peer.stdin.close()
            peer.stdin = None
        results = []
        for peer in peers:
            stdout, stderr = peer.communicate(timeout=30)
            assert peer.returncode == 0, stderr.decode(errors="replace")
            results.append(json.loads(stdout))
        return results
    finally:
        for peer in peers:
            if peer.poll() is None:
                peer.kill()
                peer.wait(timeout=5)


def test_noisy_server_cannot_take_quiet_servers_normal_or_critical_slots(tmp_path):
    path = tmp_path / "shared.db"
    limits = JournalLimits(max_operation_rows=12, reserved_operation_rows=2,
                           server_operation_rows=5,
                           server_reserved_operation_rows=1,
                           session_operation_rows=3,
                           session_reserved_operation_rows=1)
    SQLiteJournal(path, limits=limits).close()
    specs = [("noisy", f"noisy-{index}", f"noisy-op-{index}")
             for index in range(3)]
    specs.append(("quiet", "quiet-session", "quiet-op"))
    results = run_peers(path, limits, specs, 20)
    assert sum(len(item["admitted"]) for item in results[:3]) == 4
    assert len(results[3]["admitted"]) == 2
    assert all(len(item["admitted"]) <= 2 for item in results)
    assert all(len(item["admitted"]) + item["denied"] == 20
               for item in results)

    async def verify():
        journal = SQLiteJournal(path, limits=limits)
        try:
            assert journal._db.execute(
                "SELECT operation_rows FROM operation_usage").fetchone()[0] == 6
            assert journal._db.execute(
                "SELECT operation_rows FROM server_operation_usage WHERE server_id='noisy'").fetchone()[0] == 4
            assert journal._db.execute(
                "SELECT operation_rows FROM server_operation_usage WHERE server_id='quiet'").fetchone()[0] == 2
            _, fresh = await journal.admit(
                OperationKey("noisy", "executor", "noisy-critical"),
                "critical", "noisy-0", critical=True)
            assert fresh
            _, fresh = await journal.admit(
                OperationKey("quiet", "executor", "quiet-critical"),
                "critical", "quiet-session", critical=True)
            assert fresh
            with pytest.raises(CoreError, match="JOURNAL_FULL"):
                await journal.admit(
                    OperationKey("noisy", "executor", "noisy-critical-denied"),
                    "critical", "noisy-1", critical=True)
            prior = next(item for item in results[:3] if item["admitted"])
            operation_id = prior["admitted"][0]
            receipt, fresh = await journal.admit(
                OperationKey("noisy", "executor", operation_id),
                f"intent-{operation_id}", prior["session"])
            assert not fresh and receipt.operation_id == operation_id
        finally:
            journal.close()

    asyncio.run(verify())


def test_four_processes_cannot_oversubscribe_global_slots(tmp_path):
    path = tmp_path / "shared-global.db"
    limits = JournalLimits(max_operation_rows=3, reserved_operation_rows=0,
                           server_operation_rows=10,
                           server_reserved_operation_rows=0,
                           session_operation_rows=10,
                           session_reserved_operation_rows=0)
    SQLiteJournal(path, limits=limits).close()
    specs = [(f"server-{index}", f"session-{index}", f"operation-{index}")
             for index in range(4)]
    results = run_peers(path, limits, specs, 8)
    assert sum(len(item["admitted"]) for item in results) == 3
    assert sum(item["denied"] for item in results) == 29
    journal = SQLiteJournal(path, limits=limits)
    try:
        assert journal._db.execute(
            "SELECT operation_rows FROM operation_usage").fetchone()[0] == 3
        assert journal._db.execute(
            "SELECT COUNT(*) FROM operations_v2").fetchone()[0] == 3
    finally:
        journal.close()


def test_critical_writers_share_hard_global_server_and_session_caps(tmp_path):
    path = tmp_path / "shared-critical.db"
    limits = JournalLimits(max_operation_rows=6, reserved_operation_rows=2,
                           server_operation_rows=4,
                           server_reserved_operation_rows=1,
                           session_operation_rows=3,
                           session_reserved_operation_rows=1)
    SQLiteJournal(path, limits=limits).close()
    specs = [(f"server-{server}", f"session-{server}-{session}",
              f"critical-{server}-{session}")
             for server in range(2) for session in range(2)]
    results = run_peers(path, limits, specs, 8, critical=True)
    assert sum(len(item["admitted"]) for item in results) == 6
    assert sum(item["denied"] for item in results) == 26
    assert all(len(item["admitted"]) <= 3 for item in results)
    assert all(sum(len(item["admitted"]) for item in results
                   if item["server"] == f"server-{server}") <= 4
               for server in range(2))
    journal = SQLiteJournal(path, limits=limits)
    try:
        assert journal._db.execute(
            "SELECT operation_rows FROM operation_usage").fetchone()[0] == 6
        assert journal._db.execute(
            "SELECT COUNT(*) FROM operations_v2").fetchone()[0] == 6
    finally:
        journal.close()
