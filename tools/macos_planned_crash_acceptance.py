"""Installed-wheel owner-crash cuts for the Darwin launchd guardian.

Run with a wheel-only venv in a supported macOS GUI login session. Every owner
and native child belongs to a disposable fixture; no user process is signalled.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import CoreError, SessionKey
from nexus_connector_core.native.process.launch_exclusion import HostLaunchExclusion
from nexus_connector_core.native.process.preflight import containment_preflight
from nexus_connector_core.native.process.recovery import recover_launch_container
from nexus_connector_core.process_launch_control import ProcessLaunchController
from nexus_connector_core.slot_ledger import SQLiteOwnedSlotLedger


async def inspect(directory, boundary):
    journal = SQLiteJournal(directory / 'journal.db')
    ledger = SQLiteOwnedSlotLedger(directory / 'owned-slots.db')
    try:
        key = SessionKey('server', 'executor', 'session')
        launch = await journal.get_process_launch(key)
        assert launch is not None and launch.identity.platform == 'darwin'
        assert launch.spawn_claimed == (boundary != 'intent')
        assert (await journal.get_process_birth(key) is not None) == (boundary == 'birth')
        controller = ProcessLaunchController(journal, HostLaunchExclusion())
        expected = 'CONTAINER_UNCERTAIN' if boundary == 'claim' else 'STOPPED'
        deadline = time.monotonic() + 30
        while True:
            recovered = await controller.recover(
                launch.identity, validate_authority=lambda: None,
                stop_container=recover_launch_container)
            if (recovered.state == expected or boundary == 'claim'
                    or time.monotonic() >= deadline):
                break
            await asyncio.sleep(.1)
        assert recovered.state == expected, (boundary, recovered.state)
        expected_proof = {'intent': 'NEVER_CLAIMED', 'claim': None,
                          'spawn': 'CONTAINER_STOPPED',
                          'birth': 'CONTAINER_STOPPED'}[boundary]
        assert recovered.record.stop_proof == expected_proof
        assert (await ledger.owned_slot_page()).reservations
        try:
            await controller.produce(
                launch.identity, validate_authority=lambda: None,
                start=lambda: (_ for _ in ()).throw(
                    AssertionError('late producer launched')))
        except CoreError as error:
            assert error.code == 'PROCESS_LAUNCH_FENCED'
        else:
            raise AssertionError('old producer was not fenced')
        return dict(boundary=boundary, state=recovered.state,
                    stop_proof=expected_proof,
                    birth_recorded=boundary == 'birth')
    finally:
        await journal.aclose()
        await ledger.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'darwin', 'Native Darwin acceptance requires macOS'
    assert containment_preflight().get('session_domain') == 'ok', (
        'Native Darwin acceptance requires a supported gui/<uid> launchd domain')
    fixture = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launch_crash_peer.py'
    rows = []
    for boundary in ('intent', 'claim', 'spawn', 'birth'):
        with tempfile.TemporaryDirectory(prefix='nexus-macos-launch-') as root:
            directory = Path(root)
            result = subprocess.run(
                [sys.executable, '-I', str(fixture), str(directory), boundary],
                capture_output=True, text=True, timeout=30)
            assert result.returncode == 17, (boundary, result.returncode, result.stderr)
            rows.append(asyncio.run(inspect(directory, boundary)))
    report = dict(platform=sys.platform, python=sys.version.split()[0],
                  installed_core=str(Path(__import__('nexus_connector_core').__file__).resolve()),
                  results=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Darwin installed planned-launch crash cuts: 4/4 passed')


if __name__ == '__main__':
    main()
