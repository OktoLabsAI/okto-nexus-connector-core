import copy
import json
from importlib.resources import files

import pytest

from nexus_connector_core import CAPACITY_CONTRACT_REVISION, CoreError, verify_capacity_bundle
from nexus_connector_core.capacity_bundle import capacity_schema_validator


def test_packaged_bundle_covers_each_frame_and_retained_reservation_state():
    info = verify_capacity_bundle()
    assert info['revision'] == CAPACITY_CONTRACT_REVISION
    assert info['status'] == 'development'  # Host qualification is still pending.
    assert info['supported_frames'] == [
        'capacity.assess', 'capacity.changed', 'capacity.consume', 'capacity.dispatch_state', 'capacity.get',
        'capacity.release', 'capacity.reserve', 'capacity.result']
    assert info['valid_fixtures'] == 16 and info['invalid_fixtures'] == 13


def test_schema_rejects_fields_belonging_to_other_message_variants():
    fixtures = json.loads(files('nexus_connector_core').joinpath('contracts', 'capacity', 'v2', 'fixtures.json').read_bytes())
    validator = capacity_schema_validator()
    for sample in fixtures['valid']:
        frame = copy.deepcopy(sample['frame'])
        assert validator.is_valid(frame)
        extra = 'request' if frame['type'] in ('capacity.result', 'capacity.changed') else 'capacity_revision'
        frame[extra] = fixtures['valid'][0]['frame']['request'] if extra == 'request' else 1
        assert not validator.is_valid(frame)


def test_resource_drift_is_detected_before_decoding(monkeypatch, tmp_path):
    import nexus_connector_core.capacity_bundle as bundle
    real = files('nexus_connector_core').joinpath('contracts', 'capacity', 'v2')
    target = tmp_path / 'contracts' / 'capacity' / 'v2'
    target.mkdir(parents=True)
    for name in ('schema.json', 'manifest.json', 'fixtures.json'):
        (target / name).write_bytes(real.joinpath(name).read_bytes())
    (target / 'schema.json').write_bytes(b'{}')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(bundle, 'files', lambda _: tmp_path)
            bundle._bundle.cache_clear()
            bundle.capacity_schema_validator.cache_clear()
            with pytest.raises(CoreError, match='CONTRACT_BUNDLE_INVALID'):
                verify_capacity_bundle()
    finally:
        bundle._bundle.cache_clear()
        bundle.capacity_schema_validator.cache_clear()
