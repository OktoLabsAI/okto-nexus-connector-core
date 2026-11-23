"""The saved-context probe crosses the link without carrying native history."""

import pytest

from nexus_connector_core.control_codec import decode_control_frame
from nexus_connector_core.models import CoreError
from nexus_connector_core.protocol import canonical_json
from nexus_connector_core.saved_context_link import (
    MAX_SAVED_CODEX_FRAME_BYTES, SAVED_CODEX_LINK_REVISION, SAVED_CODEX_PROBE,
    decode_saved_codex_frame, encode_saved_codex_frame, saved_codex_result,
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
