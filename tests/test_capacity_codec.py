import json

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.capacity_codec import encode_capacity_frame, decode_capacity_frame
from test_capacity_contract import request, consumed


def frame(kind='capacity.reserve'):
    req = request()
    return dict(contract_revision=req.contract_revision, type=kind, server_id='server', executor_id='executor',
        connection_id='connection-1', connection_generation=1, request_id='rpc-1', request=req.to_dict())


@pytest.mark.parametrize('kind', ['capacity.assess', 'capacity.reserve', 'capacity.get', 'capacity.consume', 'capacity.release'])
def test_control_roundtrip_and_no_nxl_operation_mutation(kind):
    value = frame(kind)
    if kind == 'capacity.consume':
        value.update(reservation_id='r', consumption=consumed().to_dict())
    if kind == 'capacity.release':
        value.update(reservation_id='r', reason='LOST')
    assert decode_capacity_frame(encode_capacity_frame(value)) == value
    from nexus_connector_core import decode_r4_frame
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_r4_frame(encode_capacity_frame(value))


@pytest.mark.parametrize('change', [
    {'server_id': 'other'}, {'executor_id': 'other'}, {'connection_generation': 2},
    {'connection_generation': True}, {'payload': 'private'}, {'type': 'operation.submit'},
])
def test_acquisition_rejects_cross_host_stale_and_unexpected_fields(change):
    with pytest.raises(CoreError):
        encode_capacity_frame(frame() | change)


def test_lookup_of_original_attempt_is_permitted_after_reconnection():
    value = frame('capacity.get') | {'connection_generation': 2}
    assert decode_capacity_frame(encode_capacity_frame(value)) == value


def test_ambiguous_json_and_large_frames_are_rejected():
    raw = json.dumps(frame()).encode()
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        decode_capacity_frame(raw[:-1] + b',"request_id":"second"}')
    with pytest.raises(CoreError, match='CAPACITY_EXCEEDED'):
        decode_capacity_frame(b' ' * 16385)


def test_response_must_correlate_the_immutable_request():
    from nexus_connector_core import CapacityReservation
    value = frame()
    req = request()
    del value['request']
    value.update(type='capacity.result', request_hash=req.request_hash, result_type='reservation',
                 result=CapacityReservation('r', req, 'HELD', 1, 500, None).to_dict())
    assert decode_capacity_frame(encode_capacity_frame(value)) == value
    with pytest.raises(CoreError):
        encode_capacity_frame(value | {'request_hash': 'sha256:' + 'f' * 64})
