"""The same bounded, immutable contract is used by embedded and remote hosts."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from nexus_connector_core import (
    CAPACITY_CONTRACT_REVISION, CapacityScope, CapacityRequest,
    CapacityAssessment, CapacityConsumption, CapacityReservation,
    capacity_contract_supported, require_same_capacity_request,
)


def request(unit='next_turn'):
    return CapacityRequest(CAPACITY_CONTRACT_REVISION, 'attempt-1',
        CapacityScope('server', 'executor', 'agent', 'binding', 'workspace',
                      'folder-binding', 'session', 1, 1, 2, 3, 4, 5, 'boot-1'),
        unit, 'sha256:' + 'a' * 64, 10_000)


def consumed(unit='next_turn'):
    return CapacityConsumption('turn-1', 'sha256:' + 'b' * 64,
        'open-1' if unit == 'new_session' else None,
        'sha256:' + 'c' * 64 if unit == 'new_session' else None)


@pytest.mark.parametrize('unit', ['next_turn', 'new_session'])
def test_roundtrip_records_and_stable_request_identity(unit):
    req = request(unit)
    wire = json.loads(json.dumps(req.to_dict()))
    assert CapacityRequest.from_dict(wire) == req
    assert CapacityRequest.from_dict(dict(reversed(list(wire.items())))).request_hash == req.request_hash
    for record in [CapacityAssessment(CAPACITY_CONTRACT_REVISION, req.request_hash, 'AVAILABLE', 1, 100),
                   CapacityReservation('reservation-1', req, 'HELD', 1, 500, None),
                   CapacityReservation('reservation-1', req, 'CONSUMED', 2, 0, consumed(unit))]:
        assert type(record).from_dict(json.loads(json.dumps(record.to_dict()))) == record
    with pytest.raises(FrozenInstanceError):
        req.scope.binding_id = 'another'


@pytest.mark.parametrize('field', [
    'server_id', 'executor_id', 'agent_id', 'binding_id', 'workspace_id',
    'workspace_binding_id', 'session_id', 'boot_id', 'connection_generation',
    'session_owner_generation', 'authorization_revision', 'configuration_revision',
    'binding_revision', 'credential_epoch',
])
def test_every_scope_fence_is_part_of_immutable_attempt(field):
    req = request()
    value = getattr(req.scope, field)
    changed = replace(req, scope=replace(req.scope, **{field: value + 1 if type(value) is int else value + '-different'}))
    assert changed.request_hash != req.request_hash
    with pytest.raises(ValueError, match='RESERVATION_CONFLICT'):
        require_same_capacity_request(CapacityReservation('r', req, 'HELD', 1, 100, None), changed)


@pytest.mark.parametrize('mutation', [
    {'ttl_ms': True}, {'ttl_ms': 60_001}, {'ttl_ms': 0}, {'ttl_ms': 12.5},
    {'attempt_id': ''}, {'attempt_id': 'a' * 257}, {'attempt_id': 'a\ud800'},
    {'attempt_id': 'line\nbreak'}, {'scope': {}}, {'unit': 'queue'},
    {'affinity_key': 'sender-session'}, {'contract_revision': 'future'},
])
def test_invalid_requests_are_rejected(mutation):
    with pytest.raises(ValueError):
        replace(request(), **mutation)


@pytest.mark.parametrize('extra', ['payload', 'session_secret', 'handoff_id', 'path'])
def test_no_business_payload_credentials_or_extra_wire_fields(extra):
    wire = request().to_dict()
    wire[extra] = 'must-not-cross-the-port'
    with pytest.raises(ValueError):
        CapacityRequest.from_dict(wire)
    wire = request().to_dict()
    wire['scope'][extra] = 'also-rejected-in-nested-scope'
    with pytest.raises(ValueError):
        CapacityRequest.from_dict(wire)


def test_expired_and_consumed_states_cannot_be_confused():
    req = request()
    with pytest.raises(ValueError, match='unconsumed'):
        CapacityReservation('r', req, 'EXPIRED_UNCONSUMED', 1, 0, consumed())
    with pytest.raises(ValueError, match='operation identity'):
        CapacityReservation('r', req, 'CONSUMED', 1, 0, None)
    with pytest.raises(ValueError, match='no remaining deadline'):
        CapacityReservation('r', req, 'RELEASED', 1, 1, None)
    # Uncertainty remains a first-class state, with or without known consumption.
    for binding in [None, consumed()]:
        state = CapacityReservation('r', req, 'NEEDS_RECONCILIATION', 1, 0, binding)
        assert state.state != 'EXPIRED_UNCONSUMED'


def test_opening_reservation_keeps_exact_first_turn_and_cannot_be_rebound():
    with pytest.raises(ValueError, match='reserved unit'):
        CapacityReservation('r', request('new_session'), 'CONSUMED', 1, 0, consumed())
    with pytest.raises(ValueError, match='reserved unit'):
        CapacityReservation('r', request(), 'CONSUMED', 1, 0, consumed('new_session'))
    with pytest.raises(ValueError, match='occur together'):
        replace(consumed('new_session'), opening_intent_hash=None)
    with pytest.raises(ValueError, match='must differ'):
        replace(consumed('new_session'), opening_operation_id='turn-1')


def test_retry_cannot_change_duration_or_unit():
    req = request()
    held = CapacityReservation('r', req, 'HELD', 1, 500, None)
    require_same_capacity_request(held, req)
    for changed in [replace(req, ttl_ms=20000), replace(req, unit='new_session'), replace(req, attempt_id='other')]:
        with pytest.raises(ValueError, match='RESERVATION_CONFLICT'):
            require_same_capacity_request(held, changed)


def test_unknown_capability_never_becomes_available():
    for peer in [None, {}, {'execution_capacity': True}, {'execution_capacity': 'next-version'}]:
        assert not capacity_contract_supported(peer)
    assert capacity_contract_supported({'execution_capacity': CAPACITY_CONTRACT_REVISION})
    for reason in ['BUSY_AFFINITY', 'EARLIER_WORK_PENDING', 'STALE_OBSERVATION', 'CAPACITY_PROTOCOL_UNSUPPORTED']:
        assert not CapacityAssessment(CAPACITY_CONTRACT_REVISION, request().request_hash, reason, 0, 0).available
