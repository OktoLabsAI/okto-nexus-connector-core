"""Negotiated release proof and ACK for one contained session on a live link.

This extension does not authorize stopping work or establish its business
outcome. The Server validates the original ownership and committed history.
"""
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files

from jsonschema import Draft202012Validator

from .frame_codec import _preflight_encode
from .frame_codec_r4 import decode_r4_frame
from .models import CoreError
from .protocol import canonical_json, strict_json

SESSION_RELEASE_REVISION = 'nexus-session-release-v1'
MAX_SESSION_RELEASE_BYTES = 16384


@lru_cache(maxsize=1)
def _bundle():
    root = files('nexus_connector_core').joinpath('contracts', 'session_release', 'v1')
    try:
        manifest = strict_json(root.joinpath('manifest.json').read_text(encoding='utf-8'))
        if (manifest['revision'] != SESSION_RELEASE_REVISION
                or manifest['negotiation_capability'] != SESSION_RELEASE_REVISION
                or manifest['max_frame_bytes'] != MAX_SESSION_RELEASE_BYTES
                or manifest['status'] not in ('development', 'executable')
                or set(manifest['sha256']) != {'schema.json', 'fixtures.json'}):
            raise ValueError('Invalid session release manifest.')
        resources = {}
        for name, digest in manifest['sha256'].items():
            raw = root.joinpath(name).read_bytes()
            if sha256(raw).hexdigest() != digest:
                raise ValueError('Session release contract drift.')
            resources[name] = strict_json(raw.decode('utf-8'))
        Draft202012Validator.check_schema(resources['schema.json'])
        return manifest, Draft202012Validator(resources['schema.json']), resources['fixtures.json']
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'session_release_bundle') from error


def decode_session_release(raw):
    if type(raw) is not bytes:
        raise ValueError('Session release frames require UTF-8 bytes.')
    if len(raw) > MAX_SESSION_RELEASE_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'session_release_decode')
    try:
        frame = strict_json(raw.decode('utf-8', errors='strict'))
        canonical_json(frame)
        if not _bundle()[1].is_valid(frame):
            raise ValueError('Invalid session release frame.')
        request = frame if frame['type'] == 'session.release' else frame['request']
        if any(request[k] != request['scope'][k] for k in ('server_id', 'executor_id')):
            raise ValueError('Session release scope changed.')
        return frame
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'session_release_decode') from error


def encode_session_release(frame):
    _preflight_encode(frame, MAX_SESSION_RELEASE_BYTES - 1)
    try:
        raw = canonical_json(frame)
    except (ValueError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'session_release_encode') from error
    if len(raw) + 1 > MAX_SESSION_RELEASE_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'session_release_encode')
    decode_session_release(raw)
    return raw + b'\n'


def session_release_accepted(request):
    original = decode_session_release(encode_session_release(request))
    if original['type'] != 'session.release':
        raise CoreError('VALIDATION_ERROR', 'session_release_ack')
    return dict(contract_revision=SESSION_RELEASE_REVISION, type='session.release.accepted', request=original)


def session_release_deferred(request):
    original = session_release_accepted(request)['request']
    return dict(contract_revision=SESSION_RELEASE_REVISION, type='session.release.deferred',
                request=original, reason='RECONCILIATION_REQUIRED')


class SessionReceiptDigest:
    """Hash a streamed, operation-ID ordered snapshot of latest wire receipts.

    Every receipt is validated and included in full, independently of transport
    acknowledgement. Callers must additionally prove publication/drain status.
    Ordering is explicit so bounded database cursors need not build a giant list.
    """
    def __init__(self):
        self._digest = sha256(b'nexus-session-release-receipts-v1\n')
        self._previous, self._identity, self._count = None, None, 0

    def add(self, value):
        frame = decode_r4_frame(canonical_json(value))
        current = tuple(frame.get(k) for k in ('server_id','executor_id','binding_id','agent_id','session_id'))
        if (frame['type'] != 'operation.receipt' or self._previous is not None and frame['operation_id'] <= self._previous
                or self._identity is not None and current != self._identity):
            raise CoreError('VALIDATION_ERROR', 'session_release_receipts')
        self._previous, self._identity = frame['operation_id'], current
        self._digest.update(canonical_json(frame) + b'\n')
        self._count += 1

    def snapshot(self):
        return self._count, 'sha256:' + self._digest.hexdigest()


def session_receipts_digest(receipts):
    digest = SessionReceiptDigest()
    for receipt in receipts:
        digest.add(receipt)
    return digest.snapshot()


def verify_session_release_bundle():
    manifest, _, fixtures = _bundle()
    for sample in fixtures['valid']:
        if decode_session_release(encode_session_release(sample['frame'])) != sample['frame']:
            raise CoreError('CONTRACT_BUNDLE_INVALID', 'session_release_fixtures')
    for sample in fixtures['invalid']:
        try:
            decode_session_release(canonical_json(sample['frame']))
        except CoreError as error:
            if error.code == sample['error_code']:
                continue
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'session_release_fixtures')
    return dict(revision=manifest['revision'], status=manifest['status'],
                valid_fixtures=len(fixtures['valid']), invalid_fixtures=len(fixtures['invalid']))
