"""The saved-context probe crosses the link without carrying native history."""

import pytest

from nexus_connector_core import R4_PREVIEW_REVISION, decode_r4_frame, r4_submit_intent_hash
from nexus_connector_core.control_codec import decode_control_frame
from nexus_connector_core.models import CoreError
from nexus_connector_core.protocol import canonical_json
from nexus_connector_core.saved_context_link import (
    CLAUDE_SAVED_CONTEXT, CODEX_SAVED_CONTEXT, PI_SAVED_CONTEXT, saved_native_session_digest,
    MAX_SAVED_CODEX_FRAME_BYTES, SAVED_CODEX_LINK_REVISION, SAVED_CODEX_PROBE,
    SAVED_CODEX_OPEN_REVISION, decode_saved_codex_frame, encode_saved_codex_frame,
    encode_saved_codex_open, saved_codex_operation_id, saved_codex_result,
)


@pytest.fixture
def probe():
    return {
        'contract_revision': SAVED_CODEX_LINK_REVISION, 'type': SAVED_CODEX_PROBE,
        'server_id': 'server', 'executor_id': 'executor', 'connection_id': 'live',
        'connection_generation': 4, 'request_id': 'observe',
        'scope': {'server_id': 'server', 'executor_id': 'executor', 'session_id': 'saved',
                  'agent_id': 'agent', 'binding_id': 'binding', 'workspace_id': 'workspace',
                  'workspace_binding_id': 'mapping', 'session_owner_generation': 1,
                  'authorization_revision': 2, 'configuration_revision': 3,
                  'binding_revision': 4, 'credential_epoch': 5},
        'source': {'opening_operation_id': 'opening', 'close_operation_id': 'close',
                   'stream_epoch': 'stream', 'source_connection_id': 'old',
                   'source_connection_generation': 3,
                   'resource_release_digest': 'sha256:' + 'c' * 64},
    }


def test_probe_and_response_need_the_negotiated_revision(probe):
    for frame in (probe, saved_codex_result(probe, available=True), saved_codex_result(probe, available=False)):
        raw = encode_saved_codex_frame(frame)
        with pytest.raises(CoreError) as absent:
            decode_control_frame(raw)
        assert absent.value.code == 'VERSION_INCOMPATIBLE'
        assert decode_control_frame(raw, capabilities=[SAVED_CODEX_LINK_REVISION]) == frame


def test_result_is_bound_to_exact_source_and_channel(probe):
    result = saved_codex_result(probe, available=True)
    changed = (
        probe | {'scope': probe['scope'] | {'session_owner_generation': 2}},
        probe | {'connection_generation': 5},
        probe | {'request_id': 'other'},
        probe | {'source': probe['source'] | {'close_operation_id': 'other-close'}},
    )
    for alternate in changed:
        assert saved_codex_result(alternate, available=True)['request_hash'] != result['request_hash']
    assert set(result) == (set(probe) - {'source', 'scope'}) | {'request_hash', 'available'}


def test_probe_rejects_private_data_native_actions_and_cross_scope(probe):
    result = saved_codex_result(probe, available=True)
    invalid = (
        probe | {'method': 'thread/resume'},
        probe | {'scope': probe['scope'] | {'executor_id': 'other'}},
        probe | {'scope': probe['scope'] | {'session_owner_generation': True}},
        probe | {'source': probe['source'] | {'rollout_path': 'private'}},
        probe | {'source': probe['source'] | {'opening_binding_digest': 'sha256:' + 'a' * 64}},
        probe | {'source': probe['source'] | {'source_connection_generation': 5}},
        probe | {'source': probe['source'] | {'source_connection_generation': 4}},
        probe | {'source': probe['source'] | {'close_operation_id': 'opening'}},
        probe | {'source': probe['source'] | {'resource_release_digest': 'fake'}},
        result | {'available': 1},
        result | {'history': ['private']},
    )
    for frame in invalid:
        with pytest.raises(CoreError) as rejected:
            decode_saved_codex_frame(canonical_json(frame))
        assert rejected.value.code == 'VALIDATION_ERROR'
    with pytest.raises(CoreError) as oversized:
        decode_saved_codex_frame(b'x' * (MAX_SAVED_CODEX_FRAME_BYTES + 1))
    assert oversized.value.code == 'CAPACITY_EXCEEDED'


def test_saved_opening_hashes_the_origin_and_requires_the_negotiated_envelope(probe):
    source_scope, source = probe['scope'], probe['source']
    scope = source_scope | {'session_id': 'successor', 'session_owner_generation': 1}
    opening = dict(scope, protocol_major=1, contract_revision=R4_PREVIEW_REVISION,
        type='operation.submit', action='runtime.open', connection_id='live', connection_generation=4,
        grant_id='grant', payload=dict(adapter_id='codex_app_server', candidate_ref='nexus-install-v1:' + 'a' * 64,
            inventory_revision='sha256:' + 'a' * 64, realization_ref='realization', realization_revision=1,
            profile_revision=1, mode='managed'))
    opening['intent_hash'] = r4_submit_intent_hash(opening)
    opening['operation_id'] = saved_codex_operation_id(scope, opening['intent_hash'], source_scope, source)
    raw = encode_saved_codex_open(opening, source_scope=source_scope, source=source)
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_control_frame(raw, capabilities=[SAVED_CODEX_LINK_REVISION])
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_control_frame(canonical_json(opening), capabilities=[SAVED_CODEX_OPEN_REVISION])
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        decode_r4_frame(canonical_json(opening | {'saved_codex_resume': True}))
    assert decode_control_frame(raw, capabilities=[SAVED_CODEX_OPEN_REVISION])['operation'] == opening
    for tampered, old in ((source_scope, source | {'close_operation_id': 'another'}),
                          (source_scope | {'binding_id': 'other'}, source),
                          (source_scope | {'session_owner_generation': 2}, source),
                          (scope, source)):
        with pytest.raises(CoreError, match='VALIDATION_ERROR'):
            encode_saved_codex_open(opening, source_scope=tampered, source=old)


@pytest.mark.parametrize('codec,native_id', [
    (CLAUDE_SAVED_CONTEXT, '51131bb3-7843-4c0e-a09b-83ec580e7c75'),
    (PI_SAVED_CONTEXT, 'hsess_51131bb378434c0ea09b83ec580e7c75'),
])
def test_saved_opening_requires_its_own_negotiation_and_exact_history_digest(probe, codec, native_id):
    digest = saved_native_session_digest(native_id)
    probe = probe | {'contract_revision': codec.link_revision, 'type': codec.probe_type}
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        codec.encode_probe(probe)
    source = probe['source'] | {'native_session_digest': digest}
    probe['source'] = source
    result = codec.result(probe, available=True)
    alternate = probe | {'source': source | {'native_session_digest': 'sha256:' + 'd' * 64}}
    assert codec.result(alternate, available=True)['request_hash'] != result['request_hash']
    for frame in (probe, result):
        raw = codec.encode_probe(frame)
        with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
            decode_control_frame(raw, capabilities=[SAVED_CODEX_LINK_REVISION])
        assert decode_control_frame(raw, capabilities=[codec.link_revision]) == frame

    source_scope = probe['scope']
    target = source_scope | {'session_id': 'successor'}
    operation = dict(target, protocol_major=1, contract_revision=R4_PREVIEW_REVISION,
        type='operation.submit', action='runtime.open', connection_id='live', connection_generation=4,
        grant_id='grant', payload=dict(adapter_id=codec.adapter_id, candidate_ref='nexus-install-v1:' + 'a' * 64,
            inventory_revision='sha256:' + 'a' * 64, realization_ref='realization', realization_revision=1,
            profile_revision=1, mode='managed'))
    operation['intent_hash'] = r4_submit_intent_hash(operation)
    operation['operation_id'] = codec.operation_id(target, operation['intent_hash'], source_scope, source)
    raw = codec.encode_open(operation, source_scope=source_scope, source=source)
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_control_frame(raw, capabilities=[codec.link_revision, SAVED_CODEX_OPEN_REVISION])
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_control_frame(canonical_json(operation), capabilities=[codec.open_revision])
    assert decode_control_frame(raw, capabilities=[codec.open_revision])['operation'] == operation
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        codec.encode_open(operation, source_scope=source_scope, source=alternate['source'])
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        CODEX_SAVED_CONTEXT.encode_open(operation, source_scope=source_scope,
            source={key: val for key, val in source.items() if key != 'native_session_digest'})

    operation['payload']['adapter_id'] = 'codex_app_server'
    operation['intent_hash'] = r4_submit_intent_hash(operation)
    operation['operation_id'] = codec.operation_id(target, operation['intent_hash'], source_scope, source)
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        codec.encode_open(operation, source_scope=source_scope, source=source)
