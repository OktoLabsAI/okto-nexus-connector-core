"""The negotiated extension has its own identity and cannot widen base R4."""
import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from nexus_connector_core import CoreError, decode_r4_frame, encode_r4_frame
from nexus_connector_core import preopen_bundle_r4 as bundle
from test_r4_development_bundle import open_frame
from test_r4_preopen_refusal import report, reconciliation


def test_preopen_overlay_extends_exact_current_reconciliation_branches():
    base = json.loads(files('nexus_connector_core.contracts.nxl.r4').joinpath('frame.schema.json').read_text())
    overlay = json.loads(files('nexus_connector_core').joinpath('contracts', 'preopen_refusal', 'v1', 'schema.json').read_text())
    branches = {item['properties']['type']['const']: item for item in base['oneOf']}
    for item in overlay['oneOf']:
        kind = item['properties']['type']['const']
        extension = {'reconcile.request': 'preopen_refusal_supported', 'reconcile.report': 'preopen_refusals'}[kind]
        item['properties'].pop(extension)
        item['required'].remove(extension)
        assert item == branches[kind]


def test_preopen_overlay_leaves_base_reconciliation_closed():
    raw = files('nexus_connector_core.contracts.nxl.r4').joinpath('frame.schema.json').read_text()
    base = Draft202012Validator(json.loads(raw))
    frame = reconciliation(report())
    with pytest.raises(ValidationError):
        base.validate(frame)
    assert decode_r4_frame(encode_r4_frame(frame)) == frame
    del frame['preopen_refusals']
    base.validate(frame)
    assert decode_r4_frame(encode_r4_frame(frame)) == frame


@pytest.mark.parametrize('field', ['preopen_refusal_supported', 'preopen_refusals'])
def test_preopen_overlay_cannot_extend_productive_operation(field):
    frame = open_frame()
    frame[field] = True if field.endswith('supported') else []
    with pytest.raises(CoreError, match='VALIDATION_ERROR'):
        encode_r4_frame(frame)


@pytest.mark.parametrize('change', ['revision', 'negotiation_capability', 'base_revision',
                                   'base_schema_sha256', 'schema_bytes'])
def test_preopen_manifest_and_resources_fail_closed(tmp_path, monkeypatch, change):
    root = files('nexus_connector_core').joinpath('contracts', 'preopen_refusal', 'v1')
    target = tmp_path / 'contracts' / 'preopen_refusal' / 'v1'
    target.mkdir(parents=True)
    manifest = json.loads(root.joinpath('manifest.json').read_text())
    schema = root.joinpath('schema.json').read_bytes()
    if change == 'schema_bytes':
        schema += b' '
    else:
        manifest[change] = 'different'
    (target / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (target / 'schema.json').write_bytes(schema)
    real_files = bundle.files
    monkeypatch.setattr(bundle, 'files', lambda name: tmp_path if name == 'nexus_connector_core' else real_files(name))
    bundle.preopen_schema_validator.cache_clear()
    try:
        with pytest.raises(CoreError, match='CONTRACT_BUNDLE_INVALID'):
            bundle.preopen_schema_validator()
    finally:
        bundle.preopen_schema_validator.cache_clear()
