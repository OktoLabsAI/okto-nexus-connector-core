"""Shared launch/recovery policy over durable storage and host exclusion ports.

Workers keep the exclusion gate on one thread. Cancelling the asynchronous
waiter does not cancel that thread or prove its native work stopped. Runtime
hosts must retain their producer task and handle, as for native startup today.
Recovery returns evidence only; capacity and operation outcomes are separate.
"""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import CoreError
from .process_launch import (ProcessLaunchIdentity, ProcessLaunchRecord, ProcessLaunchStore,
                             LaunchExclusion, LaunchGateBusy)


@dataclass(frozen=True, slots=True)
class LaunchRecovery:
    state: str
    record: ProcessLaunchRecord | None = None


class ProcessLaunchController:
    def __init__(self, store: ProcessLaunchStore, exclusion: LaunchExclusion):
        self._store = store
        self._exclusion = exclusion

    def _worker_access(self, loop, identity):
        def wait(coroutine):
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            except BaseException:
                coroutine.close()
                raise
            # No timeout can turn a pending durable claim into permission to
            # retry. This per-producer worker stays retained until I/O settles.
            return future.result()

        def read():
            record = wait(self._store.get_process_launch(identity.key))
            if record is None or record.identity != identity:
                raise CoreError('PROCESS_LAUNCH_CONFLICT', 'process_launch', possible_effect=True)
            return record

        def transition(record, action, proof=None):
            return wait(self._store.transition_process_launch(identity,
                expected_revision=record.revision, action=action, stop_proof=proof))

        return read, transition

    async def produce(self, identity: ProcessLaunchIdentity, *,
                      validate_authority: Callable[[], None],
                      start: Callable[[], Any]) -> Any:
        read, transition = self._worker_access(asyncio.get_running_loop(), identity)

        def work():
            with self._exclusion.hold(identity.producer_id):
                # Read after acquiring the OS gate, even after abandonment.
                record = read()
                validate_authority()
                transition(record, 'claim')
                # The storage await may have outlived the live lease.
                validate_authority()
                return start()

        return await asyncio.to_thread(work)

    async def recover(self, identity: ProcessLaunchIdentity, *,
                      validate_authority: Callable[[], None],
                      stop_container: Callable[[ProcessLaunchIdentity], str]) -> LaunchRecovery:
        read, transition = self._worker_access(asyncio.get_running_loop(), identity)

        def work():
            try:
                with self._exclusion.hold(identity.producer_id):
                    record = read()
                    validate_authority()
                    if record.stop_proof is not None:
                        return LaunchRecovery('STOPPED', record)
                    record = transition(record, 'fence')
                    validate_authority()
                    if not record.spawn_claimed:
                        record = transition(record, 'stop', 'NEVER_CLAIMED')
                        return LaunchRecovery('STOPPED', record)
                    # Absence is meaningful only after producer exclusion and
                    # fencing. Each platform adapter must prove its container
                    # stopped; unknown evidence retains the physical slot.
                    observation = stop_container(identity)
                    if observation != 'STOPPED':
                        return LaunchRecovery('CONTAINER_UNCERTAIN', record)
                    validate_authority()
                    record = transition(record, 'stop', 'CONTAINER_STOPPED')
                    return LaunchRecovery('STOPPED', record)
            except LaunchGateBusy:
                return LaunchRecovery('PRODUCER_BUSY')

        return await asyncio.to_thread(work)
