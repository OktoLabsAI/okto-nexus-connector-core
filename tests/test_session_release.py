import copy
import json
from importlib.resources import files

import pytest
from nexus_connector_core import CoreError, R4_PREVIEW_REVISION, decode_control_frame, decode_r4_frame
from nexus_connector_core.session_release import (
    SESSION_RELEASE_REVISION, encode_session_release, decode_session_release,
    session_release_accepted, session_release_deferred, session_receipts_digest, verify_session_release_bundle,
)


def sample():
    return json.loads(files('nexus_connector_core').joinpath(
        'contracts','session_release','v1','fixtures.json').read_bytes())['valid'][0]['frame']


def receipt(operation='a', **changes):
    return dict(protocol_major=1, contract_revision=R4_PREVIEW_REVISION, type='operation.receipt',
        server_id='server', executor_id='executor', binding_id='binding', agent_id='agent', session_id='session',
        connection_id='connection', connection_generation=1, operation_id=operation,
        intent_hash='sha256:'+'a'*64, receipt_revision=1, stage='SUCCEEDED', possible_effect=True, retry_safe=False) | changes


def test_release_bundle_and_negotiated_replies_do_not_change_r4():
    assert verify_session_release_bundle() == dict(revision=SESSION_RELEASE_REVISION, status='development',
                                                  valid_fixtures=3, invalid_fixtures=10)
    request = sample()
    for frame in (request, session_release_accepted(request), session_release_deferred(request)):
        raw = encode_session_release(frame)
        assert decode_control_frame(raw, capabilities=(SESSION_RELEASE_REVISION,)) == frame
        for caps in ((), SESSION_RELEASE_REVISION, ('unknown',)):
            with pytest.raises(CoreError):
                decode_control_frame(raw, capabilities=caps)
        with pytest.raises(CoreError):
            decode_r4_frame(raw)
    accepted = session_release_accepted(request)
    before = copy.deepcopy(accepted)
    request['scope']['session_id'] = 'different'
    assert accepted == before


@pytest.mark.parametrize('raw', [b'[]', b'{"sequence":NaN}', b'{"type":1,"type":2}', b'\xff', b' ' * 16385])
def test_release_codec_rejects_ambiguous_or_unbounded_frames(raw):
    with pytest.raises(CoreError):
        decode_session_release(raw)


def test_receipt_snapshot_covers_full_facts_and_requires_one_ordered_session():
    first, second = receipt(), receipt('b', stage='OUTCOME_UNKNOWN')
    count, digest = session_receipts_digest(iter([first, second]))
    assert count == 2 and digest.startswith('sha256:')
    assert session_receipts_digest([first, dict(second, receipt_revision=2)])[1] != digest
    assert session_receipts_digest([first, dict(second, stage='RUNNING')])[1] != digest
    for values in ([second, first], [first, first], [first, dict(second, session_id='foreign')], [sample()]):
        with pytest.raises(CoreError):
            session_receipts_digest(values)


def test_release_contract_drift_is_detected(monkeypatch, tmp_path):
    from nexus_connector_core import session_release as contract
    source = files('nexus_connector_core').joinpath('contracts','session_release','v1')
    target = tmp_path / 'contracts' / 'session_release' / 'v1'
    target.mkdir(parents=True)
    for name in ('manifest.json','schema.json','fixtures.json'):
        (target/name).write_bytes(source.joinpath(name).read_bytes())
    (target/'schema.json').write_bytes(b'{}')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(contract, 'files', lambda _: tmp_path)
            contract._bundle.cache_clear()
            with pytest.raises(CoreError, match='CONTRACT_BUNDLE_INVALID'):
                verify_session_release_bundle()
    finally:
        contract._bundle.cache_clear()
