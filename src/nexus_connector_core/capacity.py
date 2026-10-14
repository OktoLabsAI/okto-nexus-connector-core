"""Versioned, application-neutral execution-capacity contracts.

These records are not execution authority. Hosts authenticate the caller and
Core still validates the installed execution lease before any native effect.
No handoff, target, sender, payload, credential or local path crosses this port.
The extension is negotiated independently; existing immutable NXL schemas stay
unchanged until a versioned transport extension is implemented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from typing import ClassVar, Mapping

from .protocol import canonical_json

CAPACITY_CONTRACT_REVISION = 'nexus-execution-capacity-v2'
CAPACITY_REASONS = frozenset({
    'AVAILABLE', 'BUSY_AFFINITY', 'POOL_FULL', 'HOST_FULL',
    'EARLIER_WORK_PENDING', 'RECOVERING', 'STALE_OBSERVATION',
    'NOT_AUTHORIZED', 'CAPACITY_PROTOCOL_UNSUPPORTED', 'RESERVATION_CONFLICT',
    'RESERVATION_EXPIRED', 'NEEDS_RECONCILIATION',
})
RESERVATION_STATES = frozenset({
    'HELD', 'CONSUMED', 'RELEASE_PENDING', 'RELEASED',
    'EXPIRED_UNCONSUMED', 'NEEDS_RECONCILIATION',
})
MAX_CAPACITY_TTL_MS = 60_000
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _text(value, name, *, maximum=256):
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or any(ord(c) < 33 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ValueError(f'Invalid capacity {name}.')


def _integer(value, name, *, minimum=0, maximum=MAX_SAFE_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'Invalid capacity {name}.')


def _digest(value, name):
    if (type(value) is not str or len(value) != 71 or not value.startswith('sha256:')
            or any(c not in '0123456789abcdef' for c in value[7:])):
        raise ValueError(f'Invalid capacity {name}.')


class _Record:
    _nested: ClassVar[dict] = {}

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        expected = {f.name for f in fields(cls)}
        if type(value) is not dict or set(value) != expected:
            raise ValueError(f'Invalid {cls.__name__} fields.')
        values = dict(value)
        for key, record in cls._nested.items():
            if values[key] is not None:
                values[key] = record.from_dict(values[key])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class CapacityScope(_Record):
    server_id: str
    executor_id: str
    agent_id: str
    binding_id: str
    workspace_id: str
    workspace_binding_id: str
    session_id: str
    connection_generation: int
    session_owner_generation: int
    authorization_revision: int
    configuration_revision: int
    binding_revision: int
    credential_epoch: int
    boot_id: str

    def __post_init__(self):
        for name in ('server_id', 'executor_id', 'agent_id', 'binding_id',
                     'workspace_id', 'workspace_binding_id', 'session_id', 'boot_id'):
            _text(getattr(self, name), name)
        for name in ('connection_generation', 'session_owner_generation',
                     'authorization_revision', 'configuration_revision',
                     'binding_revision', 'credential_epoch'):
            _integer(getattr(self, name), name, minimum=1)


@dataclass(frozen=True, slots=True)
class CapacityRequest(_Record):
    contract_revision: str
    attempt_id: str
    scope: CapacityScope
    unit: str  # next_turn | new_session; session_id is proposed for new_session
    affinity_key: str  # opaque digest calculated by the application
    ttl_ms: int
    _nested: ClassVar[dict] = {'scope': CapacityScope}

    def __post_init__(self):
        if self.contract_revision != CAPACITY_CONTRACT_REVISION:
            raise ValueError('CAPACITY_PROTOCOL_UNSUPPORTED')
        _text(self.attempt_id, 'attempt_id')
        if type(self.scope) is not CapacityScope or self.unit not in ('next_turn', 'new_session'):
            raise ValueError('Invalid capacity unit/scope.')
        _digest(self.affinity_key, 'affinity_key')
        _integer(self.ttl_ms, 'ttl_ms', minimum=100, maximum=MAX_CAPACITY_TTL_MS)

    @property
    def request_hash(self):
        return 'sha256:' + sha256(canonical_json(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class CapacityAssessment(_Record):
    """A bounded observation, never a promise that later admission will win."""
    contract_revision: str
    request_hash: str
    reason: str
    capacity_revision: int
    valid_for_ms: int

    def __post_init__(self):
        if self.contract_revision != CAPACITY_CONTRACT_REVISION or self.reason not in CAPACITY_REASONS:
            raise ValueError('Invalid capacity assessment.')
        _digest(self.request_hash, 'request_hash')
        _integer(self.capacity_revision, 'capacity_revision')
        _integer(self.valid_for_ms, 'valid_for_ms', maximum=MAX_CAPACITY_TTL_MS)

    @property
    def available(self):
        return self.reason == 'AVAILABLE'


@dataclass(frozen=True, slots=True)
class CapacityConsumption(_Record):
    """Immutable transfer to admitted operations; open retains the first turn.

    The new-session reservation covers its opening AND its first productive
    turn. Completing the opening alone cannot allow another turn to steal it.
    Hashes are canonical execution hashes, not a second execution request.
    """
    turn_operation_id: str
    turn_intent_hash: str
    opening_operation_id: str | None
    opening_intent_hash: str | None

    def __post_init__(self):
        _text(self.turn_operation_id, 'turn_operation_id')
        _digest(self.turn_intent_hash, 'turn_intent_hash')
        if (self.opening_operation_id is None) != (self.opening_intent_hash is None):
            raise ValueError('Opening identity and hash must occur together.')
        if self.opening_operation_id is not None:
            _text(self.opening_operation_id, 'opening_operation_id')
            _digest(self.opening_intent_hash, 'opening_intent_hash')
            if self.opening_operation_id == self.turn_operation_id:
                raise ValueError('Opening and turn identities must differ.')


@dataclass(frozen=True, slots=True)
class CapacityReservation(_Record):
    reservation_id: str
    request: CapacityRequest
    state: str
    capacity_revision: int
    remaining_ms: int  # observation only; deadlines are enforced by the host
    consumption: CapacityConsumption | None
    _nested: ClassVar[dict] = {'request': CapacityRequest, 'consumption': CapacityConsumption}

    def __post_init__(self):
        _text(self.reservation_id, 'reservation_id')
        if type(self.request) is not CapacityRequest or self.state not in RESERVATION_STATES:
            raise ValueError('Invalid capacity reservation.')
        _integer(self.capacity_revision, 'capacity_revision', minimum=1)
        _integer(self.remaining_ms, 'remaining_ms', maximum=self.request.ttl_ms)
        if self.consumption is not None:
            if type(self.consumption) is not CapacityConsumption:
                raise ValueError('Invalid capacity consumption.')
            if self.state in ('HELD', 'EXPIRED_UNCONSUMED'):
                raise ValueError('Consumed capacity cannot become unconsumed.')
            if (self.request.unit == 'new_session') != (self.consumption.opening_operation_id is not None):
                raise ValueError('Consumption does not match the reserved unit.')
        elif self.state == 'CONSUMED':
            raise ValueError('Consumed reservation requires operation identity.')
        if self.state in ('EXPIRED_UNCONSUMED', 'RELEASED') and self.remaining_ms:
            raise ValueError('Released capacity has no remaining deadline.')


def require_same_capacity_request(reservation: CapacityReservation, request: CapacityRequest):
    """Retry/reconnect never extends a deadline or changes the reserved scope."""
    if reservation.request != request:
        raise ValueError('RESERVATION_CONFLICT')


@dataclass(frozen=True, slots=True)
class CapacityReservationPage:
    """Durable active facts, without interpreting another owner's clock."""
    reservations: tuple[CapacityReservation, ...]
    high_water_rowid: int
    next_after_rowid: int | None


def capacity_contract_supported(advertised: Mapping) -> bool:
    """Absence or a future incompatible revision never means idle capacity."""
    return isinstance(advertised, Mapping) and advertised.get('execution_capacity') == CAPACITY_CONTRACT_REVISION
