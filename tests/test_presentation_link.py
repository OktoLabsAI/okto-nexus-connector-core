"""Presentation transport has no operation methods and needs mutual negotiation."""

import pytest
from nexus_connector_core.control_codec import decode_control_frame
from nexus_connector_core.models import CoreError
from nexus_connector_core.presentation_link import (
    PRESENTATION_LINK_REVISION,
    PRESENTATION_READ,
    decode_presentation_frame,
    encode_presentation_frame,
    presentation_request_hash,
    presentation_result,
)
from nexus_connector_core.protocol import canonical_json


def test_negotiated_presentation_codec_binds_generation_target_and_request_without_native_methods():
    scope = {'server_id': 's', 'executor_id': 'e', 'binding_id': 'b', 'agent_id': 'a', 'session_id': 'session',
                 'workspace_id': 'w', 'workspace_binding_id': 'wb', 'session_owner_generation': 1, 'binding_revision': 1,
                 'credential_epoch': 1, 'authorization_revision': 2, 'configuration_revision': 3}
    frame = {'contract_revision': PRESENTATION_LINK_REVISION, 'type': PRESENTATION_READ, 'server_id': 's', 'executor_id': 'e',
                 'connection_id': 'c', 'connection_generation': 2, 'request_id': 'first',
                 'scope': scope, 'thread_id': 'bdfe5b81-54cf-43cf-8001-5de670d3dd69',
                 'target': {'adapter_id': 'codex_app_server', 'native_session_id': 'owned',
                             'opening_operation_id': 'opening', 'stream_epoch': 'stream'}}
    raw = encode_presentation_frame(frame)
    with pytest.raises(CoreError) as unavailable:
        decode_control_frame(raw)
    assert unavailable.value.code == 'VERSION_INCOMPATIBLE'
    assert decode_control_frame(raw, capabilities=[PRESENTATION_LINK_REVISION]) == frame
    result = presentation_result(frame, None)
    assert decode_presentation_frame(encode_presentation_frame(result)) == result
    assert result['request_hash'] == presentation_request_hash(frame)
    assert result['request_hash'] != presentation_request_hash(frame | {'scope': scope | {'session_owner_generation': 2}})
    assert result['request_hash'] != presentation_request_hash(frame | {'connection_generation': 3})
    for invalid in (frame | {'method': 'thread/start'}, frame | {'context': 'anything'},
                    frame | {'target': frame['target'] | {'adapter_id': 'pi_rpc'}},
                    frame | {'scope': scope | {'executor_id': 'other'}},
                    frame | {'connection_generation': True},
                    result | {'context': {'provider_key': 'fixture'}}):
        with pytest.raises(CoreError):
            decode_presentation_frame(canonical_json(invalid))
