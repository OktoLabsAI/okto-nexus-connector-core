"""Disposable owner, terminated only at a caller-selected launch boundary."""
import asyncio
import os
from pathlib import Path
import sys
import time

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import ExecutionContext, OperationKey, SessionKey
from nexus_connector_core.native.process import spawn_owned_process, snapshot_owned_process_birth
from nexus_connector_core.native.process.launch_exclusion import HostLaunchExclusion
from nexus_connector_core.native.process.launch_identity import plan_process_launch
from nexus_connector_core.process_launch_control import ProcessLaunchController
from nexus_connector_core.slot_ledger import SQLiteOwnedSlotLedger


async def main():
    directory, boundary = Path(sys.argv[1]), sys.argv[2]
    journal = SQLiteJournal(directory/'journal.db')
    key = SessionKey('server', 'executor', 'session')
    operation = OperationKey('server', 'executor', 'open')
    context = ExecutionContext('server','executor','binding','agent','workspace',1,1,2,
        time.monotonic()+60, frozenset({'runtime.open'}), session_owner_generation=3)
    launch = plan_process_launch(key, 'open', context)
    ledger = SQLiteOwnedSlotLedger(directory/'owned-slots.db')
    await ledger.reserve_owned_slot(operation, key.session_id)
    await journal.admit(operation, 'intent', key.session_id, claim_session=True,
        connection_generation=2, session_owner_generation=3, process_launch_identity=launch)
    if boundary == 'intent':
        os._exit(17)
    await journal.mark_possible_effect(operation)
    controller = ProcessLaunchController(journal, HostLaunchExclusion())
    if boundary == 'container':
        from nexus_connector_core.native.process.windows_process import OwnedWindowsPopen
        # Job Object already exists; the contained CreateProcess has not run.
        OwnedWindowsPopen._execute_child = lambda *_args, **_kwargs: os._exit(17)

    def start():
        if boundary == 'claim':
            os._exit(17)
        child = spawn_owned_process([sys.executable,'-c','import time; time.sleep(60)'],
            cwd=str(directory), env=dict(os.environ), container_id=launch.container_id, text=True)
        if boundary == 'spawn':
            os._exit(17)
        return child

    child = await controller.produce(launch, validate_authority=lambda: None, start=start)
    await journal.record_process_birth(operation, key.session_id, snapshot_owned_process_birth(child))
    os._exit(17)


asyncio.run(main())
