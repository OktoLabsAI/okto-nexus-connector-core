"""Negotiate a read-only probe for an exact retired Codex source."""

from hashlib import sha256
import re

from .frame_codec import _preflight_encode
from .models import CoreError
from .native_action_bridge import native_action_scope
from .protocol import canonical_json, strict_json

SAVED_CODEX_LINK_REVISION = 'nexus-saved-codex-v1'
SAVED_CODEX_PROBE = 'saved.codex.probe'
SAVED_CODEX_OBSERVED = 'saved.codex.observed'
MAX_SAVED_CODEX_FRAME_BYTES = 4096

_IDENTIFIERS = ('server_id', 'executor_id', 'connection_id', 'request_id')
_CHANNEL = frozenset((*_IDENTIFIERS, 'connection_generation', 'contract_revision', 'type'))
_SOURCE_IDS = ('source_connection_id', 'opening_operation_id', 'close_operation_id', 'stream_epoch')
_SOURCE = frozenset((*_SOURCE_IDS, 'resource_release_digest', 'source_connection_generation'))


def _identifier(value):
    return type(value) is str and 1 <= len(value) <= 160 and value.isprintable()


def _generation(value):
    return type(value) is int and 1 <= value < 2**53


def _digest(value):
    return type(value) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value) is not None


def decode_saved_codex_frame(raw: bytes) -> dict:
    if type(raw) is not bytes:
        raise ValueError('Saved context frames require UTF-8 bytes.')
    if len(raw) > MAX_SAVED_CODEX_FRAME_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'saved_codex_decode')
    try:
        frame = strict_json(raw.decode('utf-8'))
        canonical_json(frame)
        if (type(frame) is not dict or frame.get('contract_revision') != SAVED_CODEX_LINK_REVISION
                or not all(_identifier(frame.get(key)) for key in _IDENTIFIERS)
                or not _generation(frame.get('connection_generation'))):
            raise ValueError('Invalid saved context channel.')
        if frame['type'] == SAVED_CODEX_PROBE:
            if frame.keys() != _CHANNEL | {'scope', 'source'}:
                raise ValueError('Invalid saved context probe.')
            scope, source = native_action_scope(frame['scope']), frame['source']
            if (type(source) is not dict or source.keys() != _SOURCE
                    or any(scope[key] != frame[key] for key in ('server_id', 'executor_id'))
                    or not all(_identifier(source[key]) for key in _SOURCE_IDS)
                    or not _digest(source['resource_release_digest'])
                    or source['opening_operation_id'] == source['close_operation_id']
                    or not _generation(source['source_connection_generation'])
                    or source['source_connection_generation'] > frame['connection_generation']
                    or (source['source_connection_generation'] == frame['connection_generation']
                        and source['source_connection_id'] != frame['connection_id'])):
                raise ValueError('Invalid retired source.')
        elif (frame['type'] != SAVED_CODEX_OBSERVED or frame.keys() != _CHANNEL | {'request_hash', 'available'}
                or not _digest(frame['request_hash']) or type(frame['available']) is not bool):
            raise ValueError('Invalid saved context response.')
        return frame
    except (KeyError, UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'saved_codex_decode', retry_safe=True) from error


def encode_saved_codex_frame(frame: dict) -> bytes:
    _preflight_encode(frame, MAX_SAVED_CODEX_FRAME_BYTES)
    try:
        raw = canonical_json(frame)
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'saved_codex_encode', retry_safe=True) from error
    decode_saved_codex_frame(raw)
    return raw


def saved_codex_result(probe: dict, *, available: bool) -> dict:
    """Return only availability, scoped to the probe's exact canonical bytes."""
    raw = encode_saved_codex_frame(probe)
    if probe['type'] != SAVED_CODEX_PROBE or type(available) is not bool:
        raise CoreError('VALIDATION_ERROR', 'saved_codex_result', retry_safe=True)
    result = {key: probe[key] for key in _CHANNEL}
    return dict(result, type=SAVED_CODEX_OBSERVED, available=available,
                request_hash='sha256:' + sha256(raw).hexdigest())
