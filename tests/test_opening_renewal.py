"""Long preparation must follow renewals without accepting changed authority."""
import asyncio
import threading

import pytest

from nexus_connector_core import CoreError, LaunchIntent, OpenOperation, SessionKey, ShutdownPolicy, TurnOperation
from nexus_connector_core import runtime as runtime_module
from test_runtime import FakeClock, make_runtime
from test_r4_runtime_leases import attempt, grant


@pytest.mark.parametrize("adapter", ["pi_rpc", "codex_app_server", "claude_stream"])
@pytest.mark.parametrize("stage", ["prepare", "open_validation", "native"])
def test_renewal_crosses_initial_deadline_without_reopening(tmp_path, monkeypatch, adapter, stage):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock, adapter_id=adapter)
        entered, release = threading.Event(), threading.Event()
        original_prepare = runtime_module.prepare_launch
        original_open = factory.open
        count = 0

        def prepare(*args):
            nonlocal count
            count += 1
            if count == (1 if stage == "prepare" else 2) and stage != "native":
                entered.set()
                assert release.wait(5)
            return original_prepare(*args)

        async def native(*args, opening_guard, **kwargs):
            if stage == "native":
                entered.set()
                await asyncio.to_thread(release.wait, 5)
                assert not opening_guard.closed
                assert opening_guard.context_probe().lease_deadline_monotonic > clock.now
            return await original_open(*args, **kwargs)

        monkeypatch.setattr(runtime_module, "prepare_launch", prepare)
        factory.open = native
        runtime._factory_accepts_opening_guard = True
        try:
            request = await attempt(runtime, clock)
            initial = await runtime.install_r4_lease(request, grant(request))
            async def opening():
                prepared = await runtime.prepare(LaunchIntent("agent", "ws", adapter), initial.context)
                current = runtime._r4_leases[SessionKey("srv", "exe", "session")].context
                return await runtime.open(OpenOperation("open", "session", "epoch", prepared), current)
            task = asyncio.create_task(opening())
            assert await asyncio.to_thread(entered.wait, 5)
            clock.advance(30)
            renewal = await attempt(runtime, clock, purpose="renew")
            renewed = await runtime.install_r4_lease(renewal, grant(renewal))
            clock.advance(40)
            assert initial.context.lease_deadline_monotonic < clock.now < renewed.context.lease_deadline_monotonic
            release.set()
            assert (await asyncio.wait_for(task, 5)).stage == "SUBMITTED"
            assert factory.open_count == 1
            assert runtime._sessions[SessionKey("srv", "exe", "session")].context == renewed.context
            with pytest.raises(CoreError, match="STALE_GENERATION"):
                await runtime.submit(TurnOperation("old", "session", "not authorized"), initial.context)
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_opening_rejects_changed_permissions_and_revocation_fences_spawn(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        original_open = factory.open
        async def native(*args, opening_guard, **kwargs):
            entered.set()
            await release.wait()
            opening_guard.context_probe()
            return await original_open(*args, **kwargs)
        factory.open = native
        runtime._factory_accepts_opening_guard = True
        try:
            request = await attempt(runtime, clock)
            initial = await runtime.install_r4_lease(request, grant(request))
            prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"), initial.context)
            task = asyncio.create_task(runtime.open(OpenOperation("open", "session", "epoch", prepared), initial.context))
            await asyncio.wait_for(entered.wait(), 3)
            clock.advance(1)
            renewal = await attempt(runtime, clock, purpose="renew")
            with pytest.raises(CoreError, match="RECONNECT_BUSY"):
                await runtime.install_r4_lease(renewal, grant(renewal, ["runtime.close"]))
            revoking = asyncio.create_task(runtime.revoke_r4_lease(initial.context, authorization_revision=2))
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(CoreError, match="AGENT_REVOKED"):
                await task
            await revoking
            assert factory.open_count == 0
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())
