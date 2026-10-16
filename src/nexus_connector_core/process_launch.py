"""Durable launch identity and monotonic producer state.

These records are evidence, never permission to spawn or release capacity.
A host must hold the per-launch exclusion gate while claiming a spawn or
fencing its producer. Container observation supplies the separate stop proof.
No process arguments, environment, credentials or reusable PID authority belong
in this contract.
"""
from dataclasses import dataclass, replace
import re
from typing import ContextManager, Protocol

from .models import CoreError, SessionKey


@dataclass(frozen=True, slots=True)
class ProcessLaunchIdentity:
    key: SessionKey
    opening_operation_id: str
    connection_generation: int
    owner_generation: int
    platform: str
    containment: str
    container_id: str
    producer_id: str
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class ProcessLaunchRecord:
    identity: ProcessLaunchIdentity
    revision: int = 1
    spawn_claimed: bool = False
    producer_fenced: bool = False
    stop_proof: str | None = None

    @property
    def state(self) -> str:
        if self.stop_proof is not None:
            return 'STOPPED'
        if self.producer_fenced:
            return 'FENCED'
        return 'CLAIMED' if self.spawn_claimed else 'PREPARED'


_CONTAINERS = {
    'win32': ('windows_job', r'Global\\nexus-core-[0-9a-f]{32}'),
    'linux': ('linux_guardian', r'linux-guardian:[0-9a-f]{32}'),
    'darwin': ('darwin_launchd_coalition',
               r'darwin-launchd:ai\.oktolabs\.nexus-owned\.[0-9]+\.[0-9a-f]{16}'),
}


def validate_launch_identity(identity: ProcessLaunchIdentity) -> None:
    if not isinstance(identity, ProcessLaunchIdentity) or not isinstance(identity.key, SessionKey):
        raise ValueError('Invalid process launch identity')
    if type(identity.schema_version) is not int or identity.schema_version != 1:
        raise ValueError('Unsupported process launch contract')
    if any(type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value)
           for value in (identity.key.server_id, identity.key.executor_id,
                         identity.key.session_id, identity.opening_operation_id)):
        raise ValueError('Invalid process launch scope')
    if any(type(value) is not int or not 1 <= value <= 9223372036854775807
           for value in (identity.connection_generation, identity.owner_generation)):
        raise ValueError('Invalid process launch generation')
    if type(identity.platform) is not str or identity.platform not in _CONTAINERS:
        raise ValueError('Invalid process launch platform')
    kind, pattern = _CONTAINERS[identity.platform]
    if (identity.containment != kind or type(identity.container_id) is not str
            or not re.fullmatch(pattern, identity.container_id)
            or type(identity.producer_id) is not str
            or not re.fullmatch(r'[0-9a-f]{32}', identity.producer_id)):
        raise ValueError('Invalid process launch container or producer')


def transition_launch(record: ProcessLaunchRecord, *, expected_revision: int,
                      action: str, stop_proof: str | None = None) -> ProcessLaunchRecord:
    """CAS reducer. Repeated reads/prepare never grant a second spawn.

    Fencing and recording the same stop proof are idempotent. A repeated claim
    is refused even with the latest revision: only its first successful CAS
    permits the producer to proceed under its still-held exclusion gate.
    """
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError('Invalid process launch revision')
    if action not in {'claim', 'fence', 'stop'} or (action != 'stop' and stop_proof is not None):
        raise ValueError('Invalid process launch transition')
    if action == 'stop' and stop_proof not in {'NEVER_CLAIMED', 'CONTAINER_STOPPED'}:
        raise ValueError('Invalid process launch stop proof')
    if expected_revision > record.revision:
        raise CoreError('PROCESS_LAUNCH_REVISION_CONFLICT', 'process_launch')
    if action == 'fence' and record.producer_fenced:
        return record
    if action == 'stop' and record.stop_proof is not None:
        if record.stop_proof != stop_proof:
            raise CoreError('PROCESS_LAUNCH_PROOF_CONFLICT', 'process_launch')
        return record
    if expected_revision != record.revision:
        raise CoreError('PROCESS_LAUNCH_REVISION_CONFLICT', 'process_launch')
    if action == 'claim':
        if record.producer_fenced or record.spawn_claimed:
            raise CoreError('PROCESS_LAUNCH_FENCED' if record.producer_fenced
                            else 'PROCESS_LAUNCH_ALREADY_CLAIMED', 'process_launch',
                            possible_effect=record.spawn_claimed, retry_safe=not record.spawn_claimed)
        return replace(record, revision=record.revision+1, spawn_claimed=True)
    if action == 'fence':
        return replace(record, revision=record.revision+1, producer_fenced=True)
    if not record.producer_fenced or (stop_proof == 'NEVER_CLAIMED' and record.spawn_claimed):
        raise CoreError('PROCESS_LAUNCH_PROOF_REQUIRED', 'process_launch')
    return replace(record, revision=record.revision+1, stop_proof=stop_proof)


class ProcessLaunchStore(Protocol):
    async def prepare_process_launch(self, identity: ProcessLaunchIdentity) -> ProcessLaunchRecord: ...
    async def get_process_launch(self, session: SessionKey) -> ProcessLaunchRecord | None: ...
    async def transition_process_launch(self, identity: ProcessLaunchIdentity, *,
        expected_revision: int, action: str, stop_proof: str | None = None) -> ProcessLaunchRecord: ...


class LaunchGateBusy(RuntimeError):
    """Another producer/recovery worker still owns this exact frontier."""


class LaunchExclusion(Protocol):
    def hold(self, producer_id: str) -> ContextManager[None]: ...
