"""A lease fenced by another route still completes physical containment."""
import asyncio
import pytest

from nexus_connector_core import EventCursor, LaunchIntent, OpenOperation, SessionKey, ShutdownPolicy
from nexus_connector_core.journal import SQLiteJournal
from tests.test_pc02_containment import ContainNative, Factory, FakeClock, _runtime, _context


@pytest.mark.parametrize("already_fenced", [False, True])
def test_watcher_completes_when_lease_was_already_fenced(tmp_path, already_fenced):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native, clock = ContainNative(), FakeClock()
        runtime = _runtime(tmp_path, journal, Factory(native), clock)
        authority = _context(clock.monotonic() + 10)
        emitted = []
        original = runtime._bounded_lease_event
        async def observe(session, binding, kind, payload):
            emitted.append(kind)
            await original(session, binding, kind, payload)
        runtime._bounded_lease_event = observe
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(OpenOperation("open", "session", "epoch", prepared), authority)
            binding = runtime._sessions[SessionKey("srv", "exe", "session")]
            task = binding.lease_task
            binding.lease_expired = already_fenced
            clock.advance(30)
            await asyncio.wait_for(asyncio.shield(task), 3)
            assert native.forced and native.closed
            assert emitted.count("core.lease_closed") == 1
            assert emitted.count("core.lease_expired") == (0 if already_fenced else 1)
            durable = [event.native_type async for event in journal.events(
                EventCursor("srv", "exe", "session", "epoch"))]
            assert durable.count("core.lease_closed") == 1
            assert durable.count("core.lease_expired") == (0 if already_fenced else 1)
        finally:
            await runtime.shutdown(ShutdownPolicy(.1, .1))
            journal.close()
    asyncio.run(run())
