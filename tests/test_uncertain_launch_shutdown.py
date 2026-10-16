"""Failed native startups converge under the original owner, without replay."""
import asyncio
import os
import sys
import threading

import pytest

from nexus_connector_core import LaunchIntent, OpenOperation, OperationKey, SessionKey, ShutdownPolicy
from nexus_connector_core.native.adapter_types import ErrorCode, NativeAdapterError
from nexus_connector_core.native.process import spawn_owned_process
from test_runtime import make_runtime, context


async def stopped(runtime, key):
    async with asyncio.timeout(20):
        while True:
            report = await runtime.shutdown(ShutdownPolicy(.05, .05))
            if report.session_outcomes.get(key) == 'already_closed':
                assert runtime.shutdown_resources()[key] == {
                    'process_state': 'STOPPED', 'release_pending': False}
                return
            await asyncio.sleep(.02)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows planned-container recovery')
@pytest.mark.parametrize('boundary', ['before_spawn', 'after_spawn'])
def test_original_owner_contains_failed_start_without_adapter_handle(tmp_path, boundary):
    async def scenario():
        runtime, journal, factory = make_runtime(tmp_path, cleanup_budget_seconds=.01)
        children = []
        calls = []
        async def failed(prepared, session_id, ctx, *, stream_epoch, process_launch):
            def start():
                calls.append(session_id)
                if boundary == 'after_spawn':
                    children.append(spawn_owned_process(
                        [sys.executable, '-c', 'import time; time.sleep(60)'],
                        cwd=str(tmp_path), env=dict(os.environ), text=True,
                        container_id=process_launch.identity.container_id))
                raise NativeAdapterError(ErrorCode.CONFIG_ERROR, 'Startup failed',
                    {'reason': 'version_probe_timeout'})
            return await process_launch.produce(validate_authority=lambda: None, start=start)
        factory.open = failed
        runtime._factory_accepts_process_launch = True
        key = SessionKey('srv', 'exe', 'session')
        try:
            ctx = context()
            prepared = await runtime.prepare(LaunchIntent('agent','ws','codex_app_server'),ctx)
            with pytest.raises(NativeAdapterError):
                await runtime.open(OpenOperation('open','session','epoch',prepared),ctx)
            original = await journal.get_receipt(OperationKey('srv','exe','open'))
            assert original.stage == 'OUTCOME_UNKNOWN' and original.possible_effect
            assert (await journal.owned_slot_state(key)).released is False
            assert await journal.get_process_birth(key) is None
            await stopped(runtime, key)
            assert (await journal.owned_slot_state(key)).released is True
            assert (await journal.get_process_launch(key)).stop_proof == 'CONTAINER_STOPPED'
            assert await journal.get_receipt(OperationKey('srv','exe','open')) == original
            assert calls == ['session']
            for child in children:
                await asyncio.to_thread(child.wait, timeout=10)
            assert all(p.poll() is not None for p in children)
        finally:
            for child in children:
                child.kill()
                await asyncio.to_thread(child.wait, timeout=10)
                for stream in (child.stdin, child.stdout, child.stderr):
                    stream.close()
            await runtime.shutdown(ShutdownPolicy(.1,.1))
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows planned-container recovery')
def test_real_pi_adapter_version_failure_does_not_strand_runtime(tmp_path, monkeypatch):
    from pathlib import Path
    from nexus_connector_core import InstallationCandidate
    from nexus_connector_core.discovery import fingerprint
    from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
    from nexus_connector_core.runtime import LocalRuntimeCore
    from nexus_connector_core.journal import SQLiteJournal
    import nexus_connector_core.native.adapters.pi as pi
    import nexus_connector_core.native.runtime_bridge as bridge

    reasons = []
    def timeout(*args, **kwargs):
        reasons.append('version_probe_timeout')
        raise NativeAdapterError(ErrorCode.CONFIG_ERROR, 'Version probe deadline',
                                 {'reason': reasons[-1]})
    monkeypatch.setattr(pi, 'pi_version_observation', timeout)
    monkeypatch.setattr(bridge, 'qualified_build', lambda *a, **kw: True)
    async def scenario():
        journal = SQLiteJournal(tmp_path/'pi.db')
        candidate = InstallationCandidate('pi_rpc', sys.executable,
            fingerprint(Path(sys.executable)), 'explicit', 'selected', version='synthetic')
        async def environment(_):
            return {}
        runtime = LocalRuntimeCore(journal, CopiedAdapterFactory(environment),
            candidates={'pi_rpc':candidate}, workspace_roots={'ws':str(tmp_path)},
            cleanup_budget_seconds=.01)
        try:
            ctx = context()
            prepared = await runtime.prepare(LaunchIntent('agent','ws','pi_rpc'),ctx)
            with pytest.raises(NativeAdapterError) as failed:
                await runtime.open(OpenOperation('open','session','epoch',prepared),ctx)
            assert failed.value.details['reason'] == 'version_probe_timeout'
            key = SessionKey('srv','exe','session')
            assert await journal.get_process_birth(key) is None
            assert (await journal.get_receipt(OperationKey('srv','exe','open'))).stage == 'OUTCOME_UNKNOWN'
            await stopped(runtime,key)
            assert reasons == ['version_probe_timeout']
        finally:
            await runtime.shutdown(ShutdownPolicy(.1,.1))
            await journal.aclose()
    asyncio.run(scenario())


def test_unknown_stop_and_blocked_release_retain_one_owned_worker(tmp_path, monkeypatch):
    import nexus_connector_core.native.process.recovery as recovery
    async def scenario():
        runtime, journal, factory = make_runtime(tmp_path, cleanup_budget_seconds=.01)
        async def failed(prepared, session_id, ctx, *, stream_epoch, process_launch):
            def start():
                raise RuntimeError('No native handle returned')
            return await process_launch.produce(validate_authority=lambda: None, start=start)
        factory.open = failed
        runtime._factory_accepts_process_launch = True
        entered, release_stop = threading.Event(), threading.Event()
        observation = ['UNKNOWN']
        stops = []
        def observe(identity):
            stops.append(identity)
            entered.set()
            assert release_stop.wait(20)
            return observation[0]
        monkeypatch.setattr(recovery, 'recover_launch_container', observe)
        key = SessionKey('srv','exe','session')
        try:
            ctx = context()
            prepared = await runtime.prepare(LaunchIntent('agent','ws','codex_app_server'),ctx)
            with pytest.raises(RuntimeError, match='No native handle'):
                await runtime.open(OpenOperation('open','session','epoch',prepared),ctx)
            await runtime.shutdown(ShutdownPolicy(.01,.01))
            assert await asyncio.to_thread(entered.wait, 10)
            first = runtime._launch_recovery_tasks[key]
            for _ in range(3):
                report = await runtime.shutdown(ShutdownPolicy(0,0))
                assert report.session_outcomes[key] == 'unknown'
                assert runtime._launch_recovery_tasks[key] is first
                assert not first.cancelled()
            assert len(stops) == 1 and not (await journal.owned_slot_state(key)).released
            release_stop.set()
            await asyncio.shield(first)
            assert runtime.shutdown_resources()[key]['process_state'] == 'UNKNOWN'
            assert not (await journal.owned_slot_state(key)).released
            observation[0] = 'STOPPED'
            original_release = journal.release_owned_slot
            entered_release, allow_release = asyncio.Event(), asyncio.Event()
            releases = []
            async def held_release(*args):
                releases.append(args)
                entered_release.set()
                await allow_release.wait()
                return await original_release(*args)
            monkeypatch.setattr(journal, 'release_owned_slot', held_release)
            await runtime.shutdown(ShutdownPolicy(.01,.01))
            await asyncio.wait_for(entered_release.wait(), 10)
            for _ in range(3):
                await runtime.shutdown(ShutdownPolicy(0,0))
            assert runtime.shutdown_resources()[key] == {'process_state':'STOPPED','release_pending':True}
            assert len(stops) == 2 and len(releases) == 1
            allow_release.set()
            await stopped(runtime, key)
        finally:
            release_stop.set()
            if 'allow_release' in locals():
                allow_release.set()
            await stopped(runtime, key)
            await journal.aclose()
    asyncio.run(scenario())
