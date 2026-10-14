"""Byte-verified opt-in overlay; the base R4 wire schema stays immutable."""
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files

from jsonschema import Draft202012Validator

from .models import CoreError
from .protocol import strict_json


@lru_cache(maxsize=1)
def preopen_schema_validator():
    from .frame_codec_r4 import R4_CONTRACT_REVISION, verify_r4_bundle
    from .preopen_refusal_r4 import PREOPEN_REFUSAL_REVISION
    verify_r4_bundle()
    root = files('nexus_connector_core').joinpath('contracts', 'preopen_refusal', 'v1')
    try:
        manifest = strict_json(root.joinpath('manifest.json').read_text(encoding='utf-8'))
        raw = root.joinpath('schema.json').read_bytes()
        base = files('nexus_connector_core.contracts.nxl.r4').joinpath('frame.schema.json').read_bytes()
        if manifest != {
            'revision': PREOPEN_REFUSAL_REVISION,
            'negotiation_capability': PREOPEN_REFUSAL_REVISION,
            'base_revision': R4_CONTRACT_REVISION, 'status': 'executable',
            'base_schema_sha256': sha256(base).hexdigest(),
            'sha256': {'schema.json': sha256(raw).hexdigest()},
        }:
            raise ValueError('Invalid preopen extension manifest.')
        schema = strict_json(raw.decode('utf-8'))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except (OSError, TypeError, ValueError) as error:
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'preopen_bundle') from error
