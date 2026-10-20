"""Birth evidence must precede a managed harness's protocol handshake."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import (
    CoreError, ExecutionContext, InstallationCandidate, LaunchIntent,
    OpenOperation, OperationKey, SessionKey, ShutdownPolicy,
)
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector
from nexus_connector_core.native.adapters.pi import PiRpcConnector
from nexus_connector_core.native.process import observe_recorded_process_birth
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.runtime import LocalRuntimeCore


pytestmark = pytest.mark.skipif(
    sys.platform not in {"win32", "linux"}, reason="native containment qualification")


def _context():
    return ExecutionContext("srv", "exe", "binding", "agent", "ws", 1, 1, 3,
                            time.monotonic() + 120,
                            frozenset({"runtime.open", "runtime.close", "turn.submit"}))


def _runtime(tmp_path, monkeypatch, adapter, *, no_ack=False):
    import nexus_connector_core.native.runtime_bridge as bridge
    import nexus_connector_core.native.adapters.pi as pi
    import nexus_connector_core.native.adapters.claude_code_stream as claude

    peers = Path(__file__).parent / "fixtures"
    created = []

    def connector(**_kwargs):
        log = tmp_path / f"peer-{len(created)}.jsonl"
        if adapter == "pi_rpc":
            result = PiRpcConnector(
                command=(sys.executable, str(peers / "pi_rpc_peer.py"), str(log),
                         *(('NO_ACK_GET_STATE',) if no_ack else ())),
                cwd=str(tmp_path), handshake_timeout_s=3 if no_ack else 10)
        elif adapter == "codex_app_server":
            result = CodexAppServerConnector(
                command=(sys.executable, str(peers / "codex_app_server_peer.py"), str(log)),
                cwd=str(tmp_path), handshake_timeout_s=10)
        else:
            result = ClaudeCodeStreamConnector(
                binary=sys.executable, argv=(str(peers / "claude_stream_peer.py"),),
                cwd=str(tmp_path))
        created.append(result)
        return result

    monkeypatch.setattr(bridge, "load_adapter", lambda _: connector)
    monkeypatch.setattr(bridge, "qualified_build", lambda *a, **kw: True)
    monkeypatch.setattr(pi, "pi_version_observation", lambda *a, **kw: {"native_version": "0.85.1"})
    monkeypatch.setattr(claude, "claude_version_observation", lambda *a, **kw: {"native_version": "2.1.78"})

    async def environment(_):
        return {}

    journal = SQLiteJournal(tmp_path / "journal.db")
    factory = CopiedAdapterFactory(environment)
    candidate = InstallationCandidate(adapter, sys.executable,
        fingerprint(Path(sys.executable)), "explicit", "selected", version="synthetic")
    runtime = LocalRuntimeCore(journal, factory, candidates={adapter: candidate},
                              workspace_roots={"ws": str(tmp_path)})
    return runtime, journal, factory, created


@pytest.mark.parametrize("adapter", ["pi_rpc", "codex_app_server", "claude_stream"])
@pytest.mark.parametrize("fail_write", [False, True])
def test_birth_is_durable_before_startup_finishes_and_write_failure_contains(
        tmp_path, monkeypatch, adapter, fail_write):
    async def run():
        runtime, journal, factory, created = _runtime(tmp_path, monkeypatch, adapter)
        original = journal.record_process_birth
        entered, release = asyncio.Event(), asyncio.Event()
        births = []

        async def record(key, session_id, evidence):
            if not fail_write:
                result = await original(key, session_id, evidence)
            births.append(evidence)
            entered.set()
            await release.wait()
            if fail_write:
                # The underlying database error is retryable, but the child
                # has already been spawned. The adapter must not hide that.
                raise CoreError("JOURNAL_FULL", "process_birth", retry_safe=True)
            return result

        journal.record_process_birth = record
        task = None
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", adapter), _context())
            task = asyncio.create_task(runtime.open(
                OpenOperation("open", "session", "epoch", prepared), _context()))
            await asyncio.wait_for(entered.wait(), 20)
            assert not task.done(), "startup finished before the birth recorder returned"
            key = SessionKey("srv", "exe", "session")
            evidence = await journal.get_process_birth(key)
            launch = await journal.get_process_launch(key)
            assert launch is not None and launch.spawn_claimed
            assert launch.identity.opening_operation_id == 'open'
            assert launch.identity.container_id == births[0].container_id
            assert launch.identity.platform == births[0].platform
            assert (evidence is None) == fail_write
            assert observe_recorded_process_birth(births[0]) == "MATCHING_LIVE"
            if evidence is not None:
                assert evidence.opening_operation_id == "open"
                assert evidence.evidence == births[0]
            # Real Pi/Codex peers record incoming frames; none may arrive while
            # recording is held. Claude's startup itself is held at this point.
            log = tmp_path / "peer-0.jsonl"
            assert not log.exists() or not log.read_text().strip()
            release.set()
            if fail_write:
                with pytest.raises(CoreError) as caught:
                    await asyncio.wait_for(task, 20)
                assert caught.value.possible_effect
                assert not caught.value.retry_safe
                receipt = await journal.get_receipt(OperationKey("srv", "exe", "open"))
                assert receipt.stage != "SUBMITTED"
                assert observe_recorded_process_birth(births[0]) in {"NOT_RUNNING", "NOT_OBSERVED"}
            else:
                assert (await asyncio.wait_for(task, 20)).stage == "SUBMITTED"
                # Post-open compatibility recording remains idempotent.
                assert (await journal.get_process_birth(key)).evidence == births[0]
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            for connector in created:
                await asyncio.to_thread(connector.close)
            await runtime.shutdown(ShutdownPolicy(1, 1))
            factory.close()
            journal.close()

    asyncio.run(run())


def test_unresponsive_handshake_keeps_birth_visible_until_containment(tmp_path, monkeypatch):
    async def run():
        runtime, journal, factory, created = _runtime(
            tmp_path, monkeypatch, "pi_rpc", no_ack=True)
        task = None
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", "pi_rpc"), _context())
            task = asyncio.create_task(runtime.open(
                OpenOperation("open", "session", "epoch", prepared), _context()))

            async def handshake_started():
                log = tmp_path / "peer-0.jsonl"
                while not log.exists() or "get_state" not in log.read_text():
                    if task.done():
                        await task
                        raise AssertionError("startup completed without the handshake")
                    await asyncio.sleep(.01)

            await asyncio.wait_for(handshake_started(), 20)
            record = await journal.get_process_birth(SessionKey("srv", "exe", "session"))
            assert record is not None and not task.done()
            assert observe_recorded_process_birth(record.evidence) == "MATCHING_LIVE"
            receipt = await asyncio.wait_for(task, 20)
            assert receipt.stage == "FAILED"
            assert receipt.error_code == "NATIVE_STARTUP_FAILED"
            assert observe_recorded_process_birth(record.evidence) in {"NOT_RUNNING", "NOT_OBSERVED"}
            assert await journal.get_process_birth(record.key) == record
        finally:
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            for connector in created:
                await asyncio.to_thread(connector.close)
            await runtime.shutdown(ShutdownPolicy(1, 1))
            factory.close()
            journal.close()

    asyncio.run(run())


def test_slow_birth_recording_does_not_block_another_open(tmp_path, monkeypatch):
    async def run():
        runtime, journal, factory, created = _runtime(tmp_path, monkeypatch, "pi_rpc")
        original = journal.record_process_birth
        entered, release = asyncio.Event(), asyncio.Event()

        async def record(key, session_id, evidence):
            result = await original(key, session_id, evidence)
            if session_id == "slow":
                entered.set()
                await release.wait()
            return result

        journal.record_process_birth = record
        slow = None
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", "pi_rpc"), _context())
            slow = asyncio.create_task(runtime.open(
                OpenOperation("open-slow", "slow", "epoch", prepared), _context()))
            await asyncio.wait_for(entered.wait(), 20)
            fast = await asyncio.wait_for(runtime.open(
                OpenOperation("open-fast", "fast", "epoch", prepared), _context()), 20)
            assert fast.stage == "SUBMITTED" and not slow.done()
            records = [await journal.get_process_birth(SessionKey("srv", "exe", name))
                       for name in ("slow", "fast")]
            assert [r.opening_operation_id for r in records] == ["open-slow", "open-fast"]
            assert records[0].evidence != records[1].evidence
            release.set()
            assert (await slow).stage == "SUBMITTED"
        finally:
            release.set()
            if slow is not None:
                await asyncio.gather(slow, return_exceptions=True)
            for connector in created:
                await asyncio.to_thread(connector.close)
            await runtime.shutdown(ShutdownPolicy(1, 1))
            factory.close()
            journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["cancel_caller", "recorder_timeout", "draining"])
def test_abandoned_wait_keeps_late_birth_and_never_replays_open(
        tmp_path, monkeypatch, failure):
    async def run():
        import nexus_connector_core.native.runtime_bridge as bridge

        runtime, journal, factory, created = _runtime(tmp_path, monkeypatch, "pi_rpc")
        original = journal.record_process_birth
        entered, release, committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        births = []

        async def record(key, session_id, evidence):
            births.append(evidence)
            entered.set()
            await release.wait()
            result = await original(key, session_id, evidence)
            committed.set()
            return result

        journal.record_process_birth = record
        if failure == "recorder_timeout":
            monkeypatch.setattr(bridge, "_PROCESS_BIRTH_RECORD_TIMEOUT", .1)
        task = None
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", "pi_rpc"), _context())
            operation = OpenOperation("open", "session", "epoch", prepared)
            task = asyncio.create_task(runtime.open(operation, _context()))
            await asyncio.wait_for(entered.wait(), 20)
            if failure == "cancel_caller":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                if failure == "draining":
                    runtime._opening[SessionKey("srv", "exe", "session")].guard.closed = True
                    release.set()
                with pytest.raises(CoreError) as caught:
                    await asyncio.wait_for(task, 20)
                assert caught.value.possible_effect and not caught.value.retry_safe
            receipt = await journal.get_receipt(OperationKey("srv", "exe", "open"))
            assert receipt.stage == "OUTCOME_UNKNOWN"
            release.set()
            await asyncio.wait_for(committed.wait(), 20)
            assert (await journal.get_process_birth(
                SessionKey("srv", "exe", "session"))).evidence == births[0]

            async def stopped():
                while observe_recorded_process_birth(births[0]) == "MATCHING_LIVE":
                    await asyncio.sleep(.01)

            # A cancelled caller still has a supervised native producer. Its
            # late handle must be contained; timeout must already have stopped it.
            await asyncio.wait_for(stopped(), 20)
            assert await runtime.open(operation, _context()) == receipt
            assert len(created) == 1
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            for connector in created:
                await asyncio.to_thread(connector.close)
            await runtime.shutdown(ShutdownPolicy(1, 1))
            factory.close()
            journal.close()

    asyncio.run(run())
