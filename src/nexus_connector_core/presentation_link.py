"""Negotiated native presentation frames on an authenticated R4 link."""

from base64 import b64decode, b64encode
from hashlib import sha256
import re
from uuid import UUID

from .models import CoreError
from .native.pi_renderer import PiEditorUpdate, _EDITOR_KEYS, _MAX_INSERT_BYTES, _MAX_OUTPUT_BYTES, _valid_text
from .native_action_bridge import native_action_scope
from .protocol import canonical_json, strict_json

PRESENTATION_LINK_REVISION = 'nexus-presentation-read-v1'
PRESENTATION_READ = 'presentation.codex.read'
PRESENTATION_RESULT = 'presentation.codex.result'
MAX_PRESENTATION_LINK_BYTES = 16 * 1024
PI_PRESENTATION_LINK_REVISION = 'nexus-pi-presentation-v1'
PI_PRESENTATION_PROBE = 'presentation.pi.probe'
PI_PRESENTATION_OPEN = 'presentation.pi.open'
PI_PRESENTATION_NEXT = 'presentation.pi.next'
PI_PRESENTATION_EDIT = 'presentation.pi.edit'
PI_PRESENTATION_CLOSE = 'presentation.pi.close'
PI_PRESENTATION_RESULT = 'presentation.pi.result'
PI_PRESENTATION_REQUESTS = frozenset({PI_PRESENTATION_PROBE, PI_PRESENTATION_OPEN, PI_PRESENTATION_NEXT,
                                     PI_PRESENTATION_EDIT, PI_PRESENTATION_CLOSE})
MAX_PI_PRESENTATION_LINK_BYTES = 18 * 1024

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


_PI_COMMON = _COMMON | {'stream_id'}
_PI_FIELDS = {
    PI_PRESENTATION_PROBE: {'scope', 'target'},
    PI_PRESENTATION_OPEN: {'scope', 'target', 'columns', 'rows', 'editor'},
    PI_PRESENTATION_NEXT: set(),
    PI_PRESENTATION_EDIT: {'key', 'text', 'sequence'},
    PI_PRESENTATION_CLOSE: set(),
    PI_PRESENTATION_RESULT: {'request_hash', 'result'},
}
_PI_SIMPLE_STATES = frozenset({'available', 'opened', 'idle', 'edited', 'closed', 'refused'})


def _pi_bytes(encoded):
    if type(encoded) is not str:
        raise ValueError('Invalid Pi frame bytes')
    data = b64decode(encoded, validate=True)
    if not 1 <= len(data) <= _MAX_OUTPUT_BYTES or b64encode(data).decode('ascii') != encoded:
        raise ValueError('Invalid Pi frame bytes')
    return data


def _pi_result(document):
    if type(document) is not dict or type(document.get('state')) is not str:
        raise ValueError('Invalid Pi presentation result')
    state = document['state']
    if state in _PI_SIMPLE_STATES and document.keys() == {'state'}:
        return None
    if state == 'output' and document.keys() == {'state', 'bytes'}:
        return _pi_bytes(document['bytes'])
    if (state != 'draft' or document.keys() != {'state', 'sequence', 'draft', 'limit_reached'}
            or type(document['sequence']) is not int or not 1 <= document['sequence'] < 2**31
            or type(document['limit_reached']) is not bool):
        raise ValueError('Invalid Pi presentation result')
    draft = document['draft']
    if draft is not None:
        draft = _pi_bytes(draft).decode('utf-8')
        if document['limit_reached'] or not _valid_text(draft, _MAX_OUTPUT_BYTES):
            raise ValueError('Invalid Pi presentation draft')
    return PiEditorUpdate(document['sequence'], draft, document['limit_reached'])


def decode_pi_presentation_frame(raw: bytes) -> dict:
    if type(raw) is not bytes or len(raw) > MAX_PI_PRESENTATION_LINK_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'pi_presentation_decode')
    try:
        value = strict_json(raw.decode('utf-8'))
        if (type(value) is not dict or value.get('contract_revision') != PI_PRESENTATION_LINK_REVISION
                or not all(_identifier(value.get(key)) for key in ('server_id', 'executor_id', 'connection_id', 'request_id'))
                or type(value.get('connection_generation')) is not int
                or not 1 <= value['connection_generation'] < 2**53
                or type(value.get('stream_id')) is not str or not re.fullmatch(r'piv_[0-9a-f]{32}', value['stream_id'])):
            raise ValueError('Invalid Pi presentation identity')
        frame_type = value.get('type')
        if type(frame_type) is not str or frame_type not in _PI_FIELDS or value.keys() != _PI_COMMON | _PI_FIELDS[frame_type]:
            raise ValueError('Invalid Pi presentation frame')
        if frame_type in (PI_PRESENTATION_PROBE, PI_PRESENTATION_OPEN):
            scope, target = native_action_scope(value['scope']), value['target']
            if (any(scope[key] != value[key] for key in ('server_id', 'executor_id'))
                    or type(target) is not dict or target.keys() != _TARGET or target['adapter_id'] != 'pi_rpc'
                    or not all(_identifier(item) for item in target.values())):
                raise ValueError('Invalid Pi presentation target')
        if frame_type == PI_PRESENTATION_OPEN and (
                type(value['columns']) is not int or not 24 <= value['columns'] <= 300
                or type(value['rows']) is not int or not 8 <= value['rows'] <= 120
                or type(value['editor']) is not bool):
            raise ValueError('Invalid Pi presentation viewport')
        if frame_type == PI_PRESENTATION_EDIT:
            key = value['key']
            if (type(key) is not str or key not in _EDITOR_KEYS
                    or type(value['sequence']) is not int or not 1 <= value['sequence'] < 2**31
                    or (not _valid_text(value['text'], _MAX_INSERT_BYTES) if key == 'insert' else value['text'] is not None)):
                raise ValueError('Invalid Pi presentation key')
        if frame_type == PI_PRESENTATION_RESULT:
            if type(value['request_hash']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', value['request_hash']):
                raise ValueError('Invalid Pi presentation request hash')
            _pi_result(value['result'])
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'pi_presentation_decode', retry_safe=True) from error
    return value


def encode_pi_presentation_frame(value: dict) -> bytes:
    raw = canonical_json(value)
    decode_pi_presentation_frame(raw)
    return raw


def pi_presentation_result(request: dict, result: dict) -> dict:
    frame = {key: request[key] for key in _PI_COMMON}
    return dict(frame, type=PI_PRESENTATION_RESULT, request_hash=presentation_request_hash(request), result=result)


def encode_pi_presentation_output(value: bytes | PiEditorUpdate) -> dict:
    if type(value) is bytes:
        return {'state': 'output', 'bytes': b64encode(value).decode('ascii')}
    if isinstance(value, PiEditorUpdate):
        draft = None if value.draft is None else b64encode(value.draft.encode('utf-8')).decode('ascii')
        return {'state': 'draft', 'sequence': value.sequence, 'draft': draft, 'limit_reached': value.limit_reached}
    raise ValueError('Invalid Pi presentation output')


def decode_pi_presentation_output(result: dict) -> bytes | PiEditorUpdate:
    output = _pi_result(result)
    if output is None:
        raise ValueError('Pi presentation output was expected')
    return output
