"""Passive, negotiated Codex presentation frames on an authenticated R4 link."""

from hashlib import sha256
from uuid import UUID

from .models import CoreError
from .native_action_bridge import native_action_scope
from .protocol import canonical_json, strict_json

PRESENTATION_LINK_REVISION = 'nexus-presentation-read-v1'
PRESENTATION_READ = 'presentation.codex.read'
PRESENTATION_RESULT = 'presentation.codex.result'
MAX_PRESENTATION_LINK_BYTES = 16 * 1024

_COMMON = frozenset({'contract_revision', 'type', 'server_id', 'executor_id', 'connection_id',
                     'connection_generation', 'request_id'})
_TARGET = frozenset({'opening_operation_id', 'adapter_id', 'native_session_id', 'stream_epoch'})
_CONTEXT = frozenset({'thread_id', 'session_id', 'cwd', 'model', 'model_provider', 'status',
                      'created_at', 'updated_at', 'ephemeral', 'cli_version', 'source', 'approval_policy',
                      'approvals_reviewer', 'sandbox', 'reasoning_effort'})


def _identifier(value):
    return type(value) is str and 1 <= len(value) <= 160 and value.isprintable()


def _thread(value):
    return type(value) is str and len(value) == 36 and str(UUID(value)) == value


def decode_presentation_frame(raw: bytes) -> dict:
    if type(raw) is not bytes or len(raw) > MAX_PRESENTATION_LINK_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'presentation_decode')
    try:
        value = strict_json(raw.decode('utf-8'))
        if (type(value) is not dict or value.get('contract_revision') != PRESENTATION_LINK_REVISION
                or not all(_identifier(value.get(key)) for key in (
                    'server_id', 'executor_id', 'connection_id', 'request_id'))
                or type(value.get('connection_generation')) is not int
                or not 1 <= value['connection_generation'] < 2**53):
            raise ValueError('Invalid presentation identity')
        if value.get('type') == PRESENTATION_READ:
            if value.keys() != _COMMON | {'scope', 'target', 'thread_id'}:
                raise ValueError('Invalid presentation request')
            scope, target = native_action_scope(value['scope']), value['target']
            if (any(scope[key] != value[key] for key in ('server_id', 'executor_id'))
                    or type(target) is not dict or target.keys() != _TARGET
                    or target['adapter_id'] != 'codex_app_server'
                    or not all(_identifier(item) for item in target.values()) or not _thread(value['thread_id'])):
                raise ValueError('Invalid presentation target')
        elif value.get('type') == PRESENTATION_RESULT:
            if value.keys() != _COMMON | {'request_hash', 'context'}:
                raise ValueError('Invalid presentation response')
            digest = value['request_hash']
            if (type(digest) is not str or len(digest) != 71 or not digest.startswith('sha256:')
                    or any(char not in '0123456789abcdef' for char in digest[7:])):
                raise ValueError('Invalid presentation request hash')
            context = value['context']
            if context is not None and (type(context) is not dict or context.keys() != _CONTEXT
                    or not _thread(context['thread_id']) or not _identifier(context['session_id'])):
                raise ValueError('Invalid presentation context')
        else:
            raise ValueError('Invalid presentation frame type')
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'presentation_decode', retry_safe=True) from error
    return value


def encode_presentation_frame(value: dict) -> bytes:
    raw = canonical_json(value)
    decode_presentation_frame(raw)
    return raw


def presentation_request_hash(frame: dict) -> str:
    return 'sha256:' + sha256(canonical_json(frame)).hexdigest()


def presentation_result(request: dict, context: dict | None) -> dict:
    frame = {key: request[key] for key in _COMMON}
    return dict(frame, type=PRESENTATION_RESULT, request_hash=presentation_request_hash(request), context=context)
