"""Presentation transport has no operation methods and needs mutual negotiation."""

import pytest
from nexus_connector_core.control_codec import decode_control_frame
from nexus_connector_core.models import CoreError
from nexus_connector_core.native.pi_renderer import PiEditorUpdate
from nexus_connector_core.presentation_link import (
    MAX_PI_PRESENTATION_LINK_BYTES,
    PI_PRESENTATION_EDIT,
    PI_PRESENTATION_LINK_REVISION,
    PI_PRESENTATION_OPEN,
    decode_pi_presentation_frame,
    decode_pi_presentation_output,
    encode_pi_presentation_frame,
    encode_pi_presentation_output,
    pi_presentation_result,
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


def test_pi_presentation_uses_strict_scoped_pull_and_draft_frames():
    identity = {'contract_revision': PI_PRESENTATION_LINK_REVISION, 'server_id': 's', 'executor_id': 'e',
                'connection_id': 'c', 'connection_generation': 2, 'request_id': 'r', 'stream_id': 'piv_' + '1' * 32}
    scope = {key: identity[key] for key in ('server_id', 'executor_id')} | {
        'binding_id': 'b', 'agent_id': 'a', 'session_id': 'session', 'workspace_id': 'w', 'workspace_binding_id': 'wb',
        'session_owner_generation': 1, 'binding_revision': 1, 'credential_epoch': 1,
        'authorization_revision': 2, 'configuration_revision': 3}
    opened = identity | {'type': PI_PRESENTATION_OPEN, 'scope': scope, 'columns': 80, 'rows': 24, 'editor': True,
        'target': {'adapter_id': 'pi_rpc', 'native_session_id': 'owned', 'opening_operation_id': 'opening',
                   'stream_epoch': 'stream'}}
    raw = encode_pi_presentation_frame(opened)
    with pytest.raises(CoreError) as error:
        decode_control_frame(raw, capabilities=[PRESENTATION_LINK_REVISION])
    assert error.value.code == 'VERSION_INCOMPATIBLE'
    assert decode_control_frame(raw, capabilities=[PI_PRESENTATION_LINK_REVISION]) == opened

    edit = identity | {'type': PI_PRESENTATION_EDIT, 'sequence': 1, 'key': 'insert', 'text': 'Draft only'}
    assert decode_pi_presentation_frame(encode_pi_presentation_frame(edit)) == edit
    for invalid in (opened | {'columns': 400}, opened | {'editor': 1},
                    opened | {'target': opened['target'] | {'adapter_id': 'codex_app_server'}},
                    opened | {'scope': scope | {'executor_id': 'other'}}, edit | {'key': 'send_turn'},
                    edit | {'sequence': True}, edit | {'text': '\x1b[0m'},
                    edit | {'key': 'enter', 'text': 'do not submit'}, edit | {'provider_secret': 'fixture'}):
        with pytest.raises(CoreError):
            decode_pi_presentation_frame(canonical_json(invalid))

    for output in (b'\x1b[0m' + b'x' * (12 * 1024 - 4), PiEditorUpdate(1, 'Two words')):
        result = pi_presentation_result(edit, encode_pi_presentation_output(output))
        assert result['request_hash'] == presentation_request_hash(edit)
        assert result['request_hash'] != presentation_request_hash(edit | {'sequence': 2})
        assert decode_pi_presentation_output(decode_pi_presentation_frame(encode_pi_presentation_frame(result))['result']) == output

    with pytest.raises(CoreError) as oversized:
        decode_pi_presentation_frame(b'x' * (MAX_PI_PRESENTATION_LINK_BYTES + 1))
    assert oversized.value.code == 'CAPACITY_EXCEEDED'
