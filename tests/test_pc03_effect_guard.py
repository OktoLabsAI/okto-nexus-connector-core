"""PC03: pre-effect guard at the real dispatch frontier (thread-late, revoke)."""

import asyncio
import threading
import time
from dataclasses import replace

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, LaunchIntent, OpenOperation, SessionKey,
    ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.native.adapter_types import RuntimeCommandNotSent
from nexus_connector_core.native.runtime_bridge import (
    CopiedAdapterSession, EffectFence,
)
from nexus_connector_core.runtime import LocalRuntimeCore


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def monotonic(self):
        return self.now

    def wall_time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _SlowThreadNative:
    """Native whose dispatch thread waits on a real threading gate."""

    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.writes = []
        self.thread_gate = threading.Event()
        self.stopped = False

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        self.writes.append((verb, operation_id))

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.stopped = True
        await self.queue.put(None)

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


def test_rc_03_03_late_thread_does_not_write_under_expired_lease(tmp_path):
    """The guard runs inside the dispatch thread, at the write frontier.

    C2 reaudit §5.1: the fence must START VALID and BECOME invalid while
    the dispatch waits for the single executor worker - not be born
    already expired - and the guard must consult the live clock at the
    write, not only watcher flags.
    """
    from tests.test_c1_bridge_stubs import harness_session

    async def run():
        native = _SlowThreadNative()
        session = CopiedAdapterSession(
            native, harness_session(), session_id="public-session",
            stream_epoch="epoch",
            context=ExecutionContext(
                "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                time.monotonic() + 60,
                frozenset({"turn.submit", "turn.interrupt"})))
        clock = FakeClock(100.0)
        # Valid at admission: every flag clean, deadline in the future.
        fence = EffectFence(lambda: (False, False, False, False, False),
                            clock=clock.monotonic, lease_deadline=100.5)
        session.effect_fence = fence

        import concurrent.futures
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=1))
        release = threading.Event()
        busy = loop.run_in_executor(None, lambda: release.wait(5))
        await asyncio.sleep(0.05)  # warm the single worker with the block

        async def dispatch():
            await session.send("send_turn", {"text": "late"}, "op-late")

        task = asyncio.create_task(dispatch())
        await asyncio.sleep(0.1)  # the to_thread is queued, not yet running
        clock.advance(1.0)  # the lease expires while the thread waits
        release.set()
        await asyncio.wrap_future(busy)
        with pytest.raises(RuntimeCommandNotSent):
            await asyncio.wait_for(task, timeout=5)
        assert native.writes == [], "late thread must not write under stale lease"
        await session.close()

    asyncio.run(run())


def test_rc_03_01_expiry_during_admit_blocks_effect(tmp_path):
    """RC-03-01: lease expiring while the admission await runs."""
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()

        class AdmitAdvancing:
            def __init__(self, inner):
                self._inner = inner
                self._armed = False

            def arm(self):
                self._armed = True

            def __getattr__(self, name):
                return getattr(self._inner, name)

            async def admit(self, *args, **kwargs):
                if self._armed:
                    clock.advance(1000)
                return await self._inner.admit(*args, **kwargs)

        wrapped = AdmitAdvancing(journal)
        binary = tmp_path / "codex"
        binary.write_bytes(b"synthetic binary")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), fingerprint(binary),
            "explicit", "selected")

        class Factory:
            def __init__(self):
                self.native = _SlowThreadNative()

            async def open(self, prepared, session_id, context, *,
                           stream_epoch):
                return self.native

        factory = Factory()
        factory_native = factory.native
        runtime = LocalRuntimeCore(
            wrapped, factory, candidates={"codex_app_server": candidate},
            workspace_roots={"ws": str(tmp_path)}, clock=clock)
        authority = ExecutionContext(
            "srv", "exe", "binding", "agent", "ws", 1, 1, 3,
            clock.monotonic() + 60,
            frozenset({"runtime.open", "turn.submit", "turn.close"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared),
                authority)
            wrapped.arm()
            with pytest.raises(CoreError, match="AGENT_REVOKED"):
                await runtime.submit(
                    TurnOperation("turn", "session", "hello"), authority)
            assert factory_native.writes == []
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_rc_03_04_revoke_between_marker_and_write_blocks_effect(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()
        binary = tmp_path / "codex"
        binary.write_bytes(b"synthetic binary")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), fingerprint(binary), "explicit",
            "selected")

        class Factory:
            def __init__(self):
                self.native = _SlowThreadNative()

            async def open(self, prepared, session_id, context, *,
                           stream_epoch):
                return self.native

        factory = Factory()
        factory_native = factory.native
        runtime = LocalRuntimeCore(
            journal, factory, candidates={"codex_app_server": candidate},
            workspace_roots={"ws": str(tmp_path)}, clock=clock,
            lease_poll_seconds=0.01, lease_grace_seconds=0.05)
        authority = ExecutionContext(
            "srv", "exe", "binding", "agent", "ws", 1, 1, 3,
            clock.monotonic() + 60,
            frozenset({"runtime.open", "turn.submit", "turn.interrupt",
                       "runtime.close"}))
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            session = SessionKey("srv", "exe", "session")
            revoked = replace(authority, authorization_revision=2,
                              allowed_actions=frozenset())
            await runtime.revoke_lease(
                session, revoked, expected_connection_generation=3)
            with pytest.raises(CoreError, match="AGENT_REVOKED"):
                await runtime.submit(
                    TurnOperation("turn", "session", "hello"), authority)
            assert factory.native.writes == []
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())
