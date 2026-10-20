"""Measure retained journal registrations plus terminal capacity history.

This is a disposable storage-cost benchmark, not a CI performance assertion.
It uses only public Core ledger ports and never starts a native harness.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

from nexus_connector_core import (
    CAPACITY_CONTRACT_REVISION, CapacityRequest, CapacityScope,
    JournalLocation, SessionKey, SQLiteOwnedSlotLedger, capacity_reservation_id,
)


SERVER = 'srv_' + 'a' * 32
EXECUTOR = 'exe_' + 'b' * 32
PRIOR_LIMIT = 64 * 1024 * 1024
TARGET_LIMIT = 512 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1] / 'build' / 'mixed-slot-ledger'


def session_id(index: int) -> str:
    return f'ses_{index:032x}'


def location(index: int) -> JournalLocation:
    session = session_id(index)
    digest = hashlib.sha256((EXECUTOR + '\0' + session).encode('ascii')).hexdigest()
    return JournalLocation(f'session-{digest}.db', SessionKey(SERVER, EXECUTOR, session))


def request(index: int) -> CapacityRequest:
    scope = CapacityScope(SERVER, EXECUTOR, 'agt_' + 'c' * 32,
        'bind_' + 'd' * 31, 'wsr_' + 'e' * 32, 'wsb_' + 'f' * 32,
        session_id(index), 1, 1, 1, 1, 1, 1, 'boot_' + 'a' * 32)
    return CapacityRequest(CAPACITY_CONTRACT_REVISION, f'att_{index:032x}',
        scope, 'new_session',
        'sha256:' + hashlib.sha256(str(index).encode('ascii')).hexdigest(), 10_000)


async def measure(count: int) -> dict:
    root = ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix=f'mixed-{count}-', dir=root)).resolve()
    if not target.is_relative_to(root):
        raise RuntimeError('Benchmark target escaped its build directory.')
    ledger = None
    try:
        ledger = SQLiteOwnedSlotLedger(target / 'owned-slots.db')
        if ledger.max_storage_bytes != TARGET_LIMIT:
            raise RuntimeError('Unexpected default ledger storage budget.')
        started = time.perf_counter()
        for first in range(0, count, 128):
            await ledger.register_journal_locations(tuple(location(index)
                for index in range(first, min(first + 128, count))))
        registered_seconds = time.perf_counter() - started
        async def allocated():
            return await ledger._run(lambda db: db.execute('PRAGMA page_count').fetchone()[0]
                * db.execute('PRAGMA page_size').fetchone()[0])
        registry_bytes = await allocated()
        started = time.perf_counter()
        for index in range(count):
            candidate = request(index)
            released = await ledger.release_capacity_slot(candidate,
                capacity_reservation_id(candidate), now=10, boot_id=candidate.scope.boot_id)
            if released.state != 'RELEASED' or released.consumption is not None:
                raise RuntimeError('Unexpected capacity benchmark state.')
        capacity_seconds = time.perf_counter() - started
        mixed_bytes = await allocated()
        return dict(entries=count, registry_bytes=registry_bytes,
            mixed_bytes=mixed_bytes, capacity_increment_bytes=mixed_bytes-registry_bytes,
            exceeds_prior_64_mib=mixed_bytes > PRIOR_LIMIT,
            fits_default_512_mib=mixed_bytes < ledger.max_storage_bytes,
            registered_seconds=round(registered_seconds, 3),
            capacity_seconds=round(capacity_seconds, 3))
    finally:
        if ledger is not None:
            await ledger.aclose()
        if not target.is_relative_to(root):
            raise RuntimeError('Refusing cleanup outside the benchmark root.')
        shutil.rmtree(target)


async def main() -> None:
    counts = [int(value) for value in sys.argv[1:]] or [1_000, 10_000]
    if any(count < 1 or count > 100_000 for count in counts):
        raise ValueError('Counts must be between 1 and 100,000.')
    for count in counts:
        print(json.dumps(await measure(count), sort_keys=True), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
