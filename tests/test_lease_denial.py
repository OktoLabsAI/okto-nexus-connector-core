import copy
import json
from importlib.resources import files

import pytest

from nexus_connector_core import CoreError, decode_control_frame, decode_r4_frame
from nexus_connector_core.lease_denial import (
    LEASE_DENIAL_REVISION, decode_lease_denial, encode_lease_denial,
    lease_denial_frame, verify_lease_denial_bundle,
)


def sample():
    return json.loads(files('nexus_connector_core').joinpath(
        'contracts', 'lease_denial', 'v1', 'fixtures.json').read_bytes())['valid'][1]['frame']


def test_pinned_bundle_and_explicit_negotiation_preserve_r4():
    assert verify_lease_denial_bundle() == dict(revision=LEASE_DENIAL_REVISION,
        status='development', valid_fixtures=3, invalid_fixtures=8)
    frame = sample()
    assert lease_denial_frame(frame['request']) == frame
    raw = encode_lease_denial(frame)
    assert decode_control_frame(raw, capabilities=(LEASE_DENIAL_REVISION,)) == frame
    for capabilities in ((), (LEASE_DENIAL_REVISION + '-unknown',), LEASE_DENIAL_REVISION):
        with pytest.raises(CoreError):
            decode_control_frame(raw, capabilities=capabilities)
    with pytest.raises(CoreError):
        decode_r4_frame(raw)


@pytest.mark.parametrize('raw', [b'{"type":"lease.denied","type":"lease.denied"}',
    b'[]', b'{"request":NaN}', b'\xff', b' ' * 16385])
def test_denials_reject_ambiguous_unbounded_or_invalid_wire(raw):
    with pytest.raises(CoreError):
        decode_lease_denial(raw)


def test_frame_copies_original_request_and_forbids_any_secret_or_unscoped_error():
    request = sample()['request']
    frame = lease_denial_frame(request)
    before = copy.deepcopy(frame)
    request['scope']['agent_id'] = 'different'
    assert frame == before
    frame['request']['api_key'] = 'forbidden'
    with pytest.raises(CoreError):
        encode_lease_denial(frame)


def test_bundle_drift_is_detected(monkeypatch, tmp_path):
    from nexus_connector_core import lease_denial as contract
    source = files('nexus_connector_core').joinpath('contracts', 'lease_denial', 'v1')
    target = tmp_path / 'contracts' / 'lease_denial' / 'v1'
    target.mkdir(parents=True)
    for name in ('schema.json', 'manifest.json', 'fixtures.json'):
        (target / name).write_bytes(source.joinpath(name).read_bytes())
    (target / 'fixtures.json').write_bytes(b'{}')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(contract, 'files', lambda _: tmp_path)
            contract._bundle.cache_clear()
            with pytest.raises(CoreError, match='CONTRACT_BUNDLE_INVALID'):
                verify_lease_denial_bundle()
    finally:
        contract._bundle.cache_clear()
