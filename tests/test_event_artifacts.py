import pytest
from nexus_connector_core.event_artifacts import *
from nexus_connector_core.control_codec import decode_control_frame
from nexus_connector_core.models import CoreError


def event(text):
    return dict(server_id='srv',executor_id='exe',session_id='ses',stream_epoch='epoch',
                sequence=1,category='tool_activity',native_type='tool_result',payload={'text':text})


@pytest.mark.parametrize('size',[70000,95000,2*1024*1024])
def test_lossless_unicode_content_and_bounded_transfer(size):
    original=event('ação🙂'*(size//9))
    wire,raw=externalize_event(original)
    assert raw and len(canonical_json(wire))<65536
    base=dict(protocol_major=1,server_id='srv',executor_id='exe',binding_id='binding',agent_id='agent',
              connection_id='conn',connection_generation=1)
    chunks=list(artifact_chunks(base,wire,raw))
    assembled=b''
    for chunk in chunks:
        encoded=encode_event_artifact(chunk)
        assert len(encoded)<65536
        assert decode_control_frame(encoded,capabilities=[EVENT_ARTIFACT_REVISION])==chunk
        assert decode_event_artifact(encode_event_artifact(artifact_ack(chunk)))==artifact_ack(chunk)
        assembled+=base64.b64decode(chunk['data'])
    assert hydrate_event(wire,assembled)==original
    assert externalize_event(original)==(wire,raw)
    with pytest.raises(CoreError): hydrate_event(wire,assembled+b'x')
    with pytest.raises(CoreError): hydrate_event(dict(wire,session_id='other'),assembled)
    with pytest.raises(CoreError): decode_control_frame(encode_event_artifact(chunks[0]))


def test_small_events_remain_inline():
    original=event('hello')
    assert externalize_event(original)==(original,None)
