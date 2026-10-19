"""Native Windows containment across pre-birth owner-crash boundaries."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import CoreError, ExecutionContext, OperationKey, SessionKey
from nexus_connector_core.native.process import spawn_owned_process, snapshot_owned_process_birth
from nexus_connector_core.native.process.launch_exclusion import HostLaunchExclusion
from nexus_connector_core.native.process.launch_identity import plan_process_launch
from nexus_connector_core.native.process.recovery import recover_launch_container
from nexus_connector_core.process_launch_control import ProcessLaunchController
from nexus_connector_core.slot_ledger import SQLiteOwnedSlotLedger


def context():
    return ExecutionContext('server','executor','binding','agent','workspace',1,1,2,
        time.monotonic()+60, frozenset({'runtime.open'}), session_owner_generation=3)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native crash campaign')
@pytest.mark.parametrize('boundary', ['intent','claim','container','spawn','birth'])
def test_restart_fences_producer_and_recovers_exact_container_without_birth(tmp_path, boundary):
    fixture = Path(__file__).parent/'fixtures/launch_crash_peer.py'
    # Both source and installed runners use the exact same package/dependencies
    # as the parent, with -I excluding ambient Python/user-site selection.
    paths = json.dumps([str(Path(p).resolve()) for p in sys.path if p])
    code = 'import sys,json,runpy; sys.path[:]=json.loads(sys.argv.pop(1)); runpy.run_path(sys.argv.pop(1),run_name="__main__")'
    result = subprocess.run([sys.executable,'-I','-c',code,paths,str(fixture),str(tmp_path),boundary],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 17, result.stderr
    async def scenario():
        journal = SQLiteJournal(tmp_path/'journal.db')
        ledger = SQLiteOwnedSlotLedger(tmp_path/'owned-slots.db')
        try:
            key = SessionKey('server','executor','session')
            launch = await journal.get_process_launch(key)
            assert launch is not None and launch.spawn_claimed == (boundary != 'intent')
            assert (await journal.get_process_birth(key) is not None) == (boundary == 'birth')
            controller = ProcessLaunchController(journal, HostLaunchExclusion())
            recovered = await controller.recover(launch.identity, validate_authority=lambda: None,
                stop_container=recover_launch_container)
            assert recovered.state == 'STOPPED'
            assert recovered.record.stop_proof == ('NEVER_CLAIMED' if boundary == 'intent' else 'CONTAINER_STOPPED')
            assert (await ledger.owned_slot_page()).reservations  # host must settle original operation
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_FENCED'):
                await controller.produce(launch.identity, validate_authority=lambda: None,
                    start=lambda: pytest.fail('Late producer launched after recovery'))
        finally:
            await journal.aclose()
            await ledger.aclose()
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux guardian crash campaign')
@pytest.mark.parametrize('boundary,proved_stop', [
    ('intent', True),
    ('claim', False),
    ('spawn', True),
    ('birth', True),
])
def test_linux_restart_retains_uncertain_launch_until_guardian_proof(
        tmp_path, boundary, proved_stop):
    fixture = Path(__file__).parent / 'fixtures' / 'launch_crash_peer.py'
    paths = json.dumps([str(Path(p).resolve()) for p in sys.path if p])
    code = ('import sys,json,runpy; sys.path[:]=json.loads(sys.argv.pop(1)); '
            'runpy.run_path(sys.argv.pop(1),run_name="__main__")')
    result = subprocess.run(
        [sys.executable, '-I', '-c', code, paths, str(fixture), str(tmp_path), boundary],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 17, result.stderr

    async def scenario():
        journal = SQLiteJournal(tmp_path / 'journal.db')
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'owned-slots.db')
        try:
            key = SessionKey('server', 'executor', 'session')
            launch = await journal.get_process_launch(key)
            assert launch is not None
            assert launch.spawn_claimed == (boundary != 'intent')
            assert (await journal.get_process_birth(key) is not None) == (boundary == 'birth')
            controller = ProcessLaunchController(journal, HostLaunchExclusion())
            recovered = await controller.recover(
                launch.identity, validate_authority=lambda: None,
                stop_container=recover_launch_container)
            assert recovered.state == ('STOPPED' if proved_stop else 'CONTAINER_UNCERTAIN')
            assert recovered.record.stop_proof == (
                ('NEVER_CLAIMED' if boundary == 'intent' else 'CONTAINER_STOPPED')
                if proved_stop else None)
            assert (await ledger.owned_slot_page()).reservations
            with pytest.raises(CoreError, match='PROCESS_LAUNCH_FENCED'):
                await controller.produce(
                    launch.identity, validate_authority=lambda: None,
                    start=lambda: pytest.fail('Late producer launched after recovery'))
        finally:
            await journal.aclose()
            await ledger.aclose()

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native crash campaign')
def test_unrecorded_live_birth_stops_only_planned_job(tmp_path):
    async def scenario():
        journal = SQLiteJournal(tmp_path/'journal.db')
        key, operation = SessionKey('server','executor','session'), OperationKey('server','executor','open')
        launch = plan_process_launch(key, 'open', context())
        controller = ProcessLaunchController(journal, HostLaunchExclusion())
        processes = []
        def start(container=None):
            process = spawn_owned_process([sys.executable,'-c','import time; time.sleep(60)'],
                cwd=str(tmp_path), env=dict(os.environ), text=True, container_id=container)
            processes.append(process)
            return process
        try:
            await journal.admit(operation,'intent','session',claim_session=True,
                connection_generation=2,session_owner_generation=3,process_launch_identity=launch)
            await journal.mark_possible_effect(operation)
            target = await controller.produce(launch, validate_authority=lambda: None,
                start=lambda: start(launch.container_id))
            sibling = await asyncio.to_thread(start)
            assert snapshot_owned_process_birth(target).container_id == launch.container_id
            assert await journal.get_process_birth(key) is None
            recovered = await controller.recover(launch, validate_authority=lambda: None,
                stop_container=recover_launch_container)
            assert recovered.state == 'STOPPED'
            await asyncio.to_thread(target.wait, timeout=10)
            assert sibling.poll() is None
            assert recover_launch_container(replace(launch, platform='linux',
                containment='linux_guardian', container_id='linux-guardian:'+'a'*32)) == 'UNKNOWN'
        finally:
            for process in processes:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=10)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
            await journal.aclose()
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native crash campaign')
@pytest.mark.parametrize('container', ['', False, 'Global\\foreign-job', 'Global\\nexus-core-not-a-uuid'])
def test_invalid_planned_job_refused_before_process_creation(tmp_path, container):
    with pytest.raises(ValueError, match='planned Windows'):
        spawn_owned_process([sys.executable,'-c','raise SystemExit(99)'],
            cwd=str(tmp_path), env=dict(os.environ), text=True, container_id=container)
