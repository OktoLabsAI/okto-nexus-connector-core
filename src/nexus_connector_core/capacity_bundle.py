"""Packaged, byte-pinned contract and fixtures for the capacity extension."""
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import json

from jsonschema import Draft202012Validator

from .capacity import CAPACITY_CONTRACT_REVISION
from .models import CoreError


@lru_cache(maxsize=1)
def _bundle():
    root = files('nexus_connector_core').joinpath('contracts', 'capacity', 'v2')
    try:
        manifest = json.loads(root.joinpath('manifest.json').read_bytes())
        if (manifest['revision'] != CAPACITY_CONTRACT_REVISION or manifest['max_frame_bytes'] != 16384
                or manifest['negotiation_capability'] != CAPACITY_CONTRACT_REVISION
                or manifest['status'] not in ('development', 'executable')
                or set(manifest['sha256']) != {'schema.json', 'fixtures.json'}):
            raise ValueError('Invalid capacity manifest.')
        resources = {}
        for name, expected in manifest['sha256'].items():
            raw = root.joinpath(name).read_bytes()
            if sha256(raw).hexdigest() != expected:
                raise ValueError('Capacity contract resource changed.')
            resources[name] = json.loads(raw)
        Draft202012Validator.check_schema(resources['schema.json'])
        return manifest, resources
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'capacity_bundle') from error


@lru_cache(maxsize=1)
def capacity_schema_validator():
    _, resources = _bundle()
    return Draft202012Validator(resources['schema.json'])


def verify_capacity_bundle():
    """Conformance evidence, not authorization or provider qualification."""
    from .capacity_codec import decode_capacity_frame, encode_capacity_frame
    from .protocol import canonical_json
    manifest, resources = _bundle()
    fixtures = resources['fixtures.json']
    for sample in fixtures['valid']:
        if decode_capacity_frame(encode_capacity_frame(sample['frame'])) != sample['frame']:
            raise CoreError('CONTRACT_BUNDLE_INVALID', 'capacity_fixtures')
    for sample in fixtures['invalid']:
        try:
            decode_capacity_frame(canonical_json(sample['frame']))
        except CoreError as error:
            if error.code == sample['error_code']:
                continue
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'capacity_fixtures')
    return dict(revision=manifest['revision'], status=manifest['status'],
                valid_fixtures=len(fixtures['valid']), invalid_fixtures=len(fixtures['invalid']),
                supported_frames=sorted({f['frame']['type'] for f in fixtures['valid']}))
