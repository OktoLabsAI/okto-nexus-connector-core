import pytest

from nexus_connector_core import CoreError, R4_PREVIEW_REVISION, decode_r4_frame, encode_r4_frame


BASE = dict(protocol_major=1, contract_revision=R4_PREVIEW_REVISION, server_id='server',
            executor_id='executor', connection_id='connection', connection_generation=1, request_id='request')


def test_continuity_frames_round_trip():
    for frame in (dict(BASE, type='connection.renew'),
                  dict(BASE, type='connection.renewed', expires_in=600, binding_ids=['binding'])):
        assert decode_r4_frame(encode_r4_frame(frame)) == frame


@pytest.mark.parametrize('changes', [dict(expires_in=0), dict(expires_in=601),
    dict(expires_in=True), dict(binding_ids=['binding', 'binding']), dict(secret='unexpected')])
def test_continuity_ack_is_bounded_and_strict(changes):
    frame = dict(BASE, type='connection.renewed', expires_in=600, binding_ids=['binding'])
    frame.update(changes)
    with pytest.raises(CoreError):
        encode_r4_frame(frame)
