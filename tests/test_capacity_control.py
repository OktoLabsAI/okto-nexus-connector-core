import asyncio
import json
from dataclasses import replace

import pytest

from nexus_connector_core import (
    CAPACITY_CONTRACT_REVISION, R4_PREVIEW_REVISION, CoreError, SQLiteOwnedSlotLedger,
    ExecutionCapacity, decode_control_frame, encode_r4_frame, encode_capacity_frame,
    execute_capacity_control, capacity_result_frame,
)
from test_capacity_codec import frame
from test_capacity_contract import request
from test_capacity_runtime import Authority
from test_runtime import FakeClock


def test_router_keeps_r4_bytes_and_requires_explicit_extension_negotiation():
    heartbeat = dict(protocol_major=1, contract_revision=R4_PREVIEW_REVISION,
        type='heartbeat', server_id='server', executor_id='executor',
        connection_id='connection-1', connection_generation=1)
    assert decode_control_frame(encode_r4_frame(heartbeat)) == heartbeat
    raw = encode_capacity_frame(frame())
    for capabilities in ((), ('future-capacity',), CAPACITY_CONTRACT_REVISION):
        with pytest.raises(CoreError, match='CAPACITY_PROTOCOL_UNSUPPORTED'):
            decode_control_frame(raw, capabilities=capabilities)
    assert decode_control_frame(raw, capabilities=(CAPACITY_CONTRACT_REVISION,)) == frame()


@pytest.mark.parametrize('change', [{'type': 'heartbeat'}, {'payload': {}},
    {'contract_revision': 'future'}, {'server_id': 'other'}])
def test_negotiation_never_relaxes_payload_or_scope_validation(change):
    with pytest.raises(CoreError):
        decode_control_frame(json.dumps(frame() | change).encode(), capabilities=(CAPACITY_CONTRACT_REVISION,))


@pytest.mark.parametrize('raw', [b'[]', b'null', b'{"contract_revision":"x","contract_revision":"y"}',
    b'{"bad":NaN}', b'\xff', b'[' * 1500, b' ' * 1_048_577],
    ids=['array', 'null', 'duplicate-key', 'nonfinite', 'invalid-utf8', 'deep-json', 'oversized'])
def test_router_rejects_ambiguous_invalid_and_oversized_input(raw):
    with pytest.raises(CoreError):
        decode_control_frame(raw, capabilities=(CAPACITY_CONTRACT_REVISION,))


def test_control_mutation_lost_reply_is_recovered_from_same_durable_attempt(tmp_path):
    async def run():
        path = tmp_path / 'slots.db'
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        req = request('new_session')
        call = frame() | {'request': req.to_dict()}
        service = ExecutionCapacity(ledger, authority=Authority(), boot_id=req.scope.boot_id,
            runtime_lookup=lambda _: None, clock=FakeClock(10))
        original = await execute_capacity_control(service, call)
        assert original['result']['state'] == 'HELD'
        await service.aclose()
        ledger.close()
        # Different owner/clock: only original get/release, no expiry inferred.
        ledger = SQLiteOwnedSlotLedger(path, max_slots=1)
        service = ExecutionCapacity(ledger, authority=Authority(), boot_id='replacement',
            runtime_lookup=lambda _: None, clock=FakeClock(10000))
        try:
            found = await execute_capacity_control(service, call | {'type': 'capacity.get',
                'connection_generation': 2, 'request_id': 'lookup'})
            assert found['result']['reservation_id'] == original['result']['reservation_id']
            assert found['result']['state'] == 'HELD'
            released = await execute_capacity_control(service, call | {'type': 'capacity.release',
                'connection_generation': 2, 'request_id': 'release', 'reason': 'LOST',
                'reservation_id': found['result']['reservation_id']})
            assert released['result']['state'] == 'RELEASED'
            assert not (await ledger.owned_slot_page()).reservations
        finally:
            await service.aclose()
            ledger.close()
    asyncio.run(run())


@pytest.mark.parametrize('code,effect,reason', [('NOT_AUTHORIZED', False, 'NOT_AUTHORIZED'),
    ('STORAGE_ERROR', False, 'NEEDS_RECONCILIATION'), ('RECOVERING', True, 'NEEDS_RECONCILIATION')])
def test_uncertain_failure_never_pretends_no_reservation_exists(code, effect, reason):
    class Service:
        async def try_reserve_capacity(self, request):
            raise CoreError(code, 'test', possible_effect=effect)
    result = asyncio.run(execute_capacity_control(Service(), frame()))
    assert result['result_type'] == 'assessment'
    assert result['result']['reason'] == reason


def test_result_mapper_cannot_publish_another_attempt_or_fake_not_found():
    from nexus_connector_core import CapacityReservation
    req = replace(request(), attempt_id='another')
    with pytest.raises(CoreError):
        capacity_result_frame(frame(), CapacityReservation('r', req, 'HELD', 1, 1000, None))
    with pytest.raises(ValueError):
        capacity_result_frame(frame(), None)


def test_control_consumption_keeps_physical_capacity_until_native_release_proof(tmp_path):
    from nexus_connector_core import CapacityConsumption
    async def run():
        ledger = SQLiteOwnedSlotLedger(tmp_path / 'slots.db', max_slots=1)
        req = request('new_session')
        call = frame() | {'request': req.to_dict()}
        service = ExecutionCapacity(ledger, authority=Authority(), boot_id=req.scope.boot_id,
            runtime_lookup=lambda _: None, clock=FakeClock(10))
        try:
            assert (await execute_capacity_control(service, call | {'type': 'capacity.get'}))['result_type'] == 'not_found'
            assert (await execute_capacity_control(service, call | {'type': 'capacity.assess'}))['result']['reason'] == 'AVAILABLE'
            held = await execute_capacity_control(service, call)
            consumption = CapacityConsumption('turn', 'sha256:' + 'a' * 64, 'open', 'sha256:' + 'b' * 64)
            consumed = await execute_capacity_control(service, call | {'type': 'capacity.consume',
                'reservation_id': held['result']['reservation_id'], 'consumption': consumption.to_dict()})
            assert consumed['result']['state'] == 'CONSUMED'
            released = await execute_capacity_control(service, call | {'type': 'capacity.release',
                'reservation_id': held['result']['reservation_id'], 'reason': 'CANCELLED'})
            assert released['result']['state'] == 'RELEASE_PENDING'
            assert len((await ledger.owned_slot_page()).reservations) == 1
        finally:
            await service.aclose()
            ledger.close()
    asyncio.run(run())
