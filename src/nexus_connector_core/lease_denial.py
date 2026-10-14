"""Negotiated, correlated lease rejection; immutable R4 frames stay unchanged.

The original request contains no bearer material. Echoing it binds a denial
to the exact lease attempt, including its scope, serial and source channel.
A denial is not evidence of native termination or a resource-release receipt.
"""
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files

from jsonschema import Draft202012Validator

from .frame_codec import _preflight_encode
from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .models import CoreError
from .protocol import canonical_json, strict_json

LEASE_DENIAL_REVISION = 'nexus-lease-denial-v1'
MAX_LEASE_DENIAL_BYTES = 16384


@lru_cache(maxsize=1)
def _bundle():
    root = files('nexus_connector_core').joinpath('contracts', 'lease_denial', 'v1')
    try:
        manifest = strict_json(root.joinpath('manifest.json').read_text(encoding='utf-8'))
        if (manifest['revision'] != LEASE_DENIAL_REVISION
                or manifest['negotiation_capability'] != LEASE_DENIAL_REVISION
                or manifest['max_frame_bytes'] != MAX_LEASE_DENIAL_BYTES
                or manifest['status'] not in ('development', 'executable')
                or set(manifest['sha256']) != {'schema.json', 'fixtures.json'}):
            raise ValueError('Invalid lease denial manifest.')
        resources = {}
        for name, digest in manifest['sha256'].items():
            raw = root.joinpath(name).read_bytes()
            if sha256(raw).hexdigest() != digest:
                raise ValueError('Lease denial contract drift.')
            resources[name] = strict_json(raw.decode('utf-8'))
        Draft202012Validator.check_schema(resources['schema.json'])
        return manifest, Draft202012Validator(resources['schema.json']), resources['fixtures.json']
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'lease_denial_bundle') from error


def decode_lease_denial(raw):
    if type(raw) is not bytes:
        raise ValueError('Lease denial frames require UTF-8 bytes.')
    if len(raw) > MAX_LEASE_DENIAL_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'lease_denial_decode')
    try:
        frame = strict_json(raw.decode('utf-8', errors='strict'))
        canonical_json(frame)
        if not _bundle()[1].is_valid(frame):
            raise ValueError('Invalid lease denial frame.')
        request = decode_r4_frame(canonical_json(frame['request']))
        if request['type'] != 'lease.renew':
            raise ValueError('A lease denial requires its original renewal request.')
        return frame
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'lease_denial_decode') from error


def encode_lease_denial(frame):
    _preflight_encode(frame, MAX_LEASE_DENIAL_BYTES - 1)
    try:
        raw = canonical_json(frame)
    except (ValueError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'lease_denial_encode') from error
    if len(raw) + 1 > MAX_LEASE_DENIAL_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'lease_denial_encode')
    decode_lease_denial(raw)
    return raw + b'\n'


def lease_denial_frame(request):
    original = decode_r4_frame(encode_r4_frame(request))
    frame = dict(contract_revision=LEASE_DENIAL_REVISION, type='lease.denied',
                 request=original, code='LEASE_REVALIDATION_REQUIRED')
    return decode_lease_denial(encode_lease_denial(frame))


def verify_lease_denial_bundle():
    manifest, _, fixtures = _bundle()
    for sample in fixtures['valid']:
        if decode_lease_denial(encode_lease_denial(sample['frame'])) != sample['frame']:
            raise CoreError('CONTRACT_BUNDLE_INVALID', 'lease_denial_fixtures')
    for sample in fixtures['invalid']:
        try:
            decode_lease_denial(canonical_json(sample['frame']))
        except CoreError as error:
            if error.code == sample['error_code']:
                continue
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'lease_denial_fixtures')
    return dict(revision=manifest['revision'], status=manifest['status'],
                valid_fixtures=len(fixtures['valid']), invalid_fixtures=len(fixtures['invalid']))
