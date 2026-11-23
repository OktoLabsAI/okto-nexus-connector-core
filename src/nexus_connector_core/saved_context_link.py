"""Scoped proof and admission for resuming a retired native session."""

from dataclasses import dataclass
from hashlib import sha256
import re

from .frame_codec import _preflight_encode
from .frame_codec_r4 import decode_r4_frame
from .models import CoreError
from .native_action_bridge import native_action_scope
from .protocol import canonical_json, strict_json

MAX_SAVED_CODEX_FRAME_BYTES = 4096
MAX_SAVED_CODEX_OPEN_BYTES = 96 * 1024

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


@dataclass(frozen=True, slots=True)
class SavedContextCodec:
    adapter_id: str
    name: str
    operation_prefix: str
    native_session_digest: bool = False

    @property
    def link_revision(self):
        return f'nexus-saved-{self.name}-v1'

    @property
    def open_revision(self):
        return f'nexus-saved-{self.name}-open-v1'

    @property
    def probe_type(self):
        return f'saved.{self.name}.probe'

    @property
    def observed_type(self):
        return f'saved.{self.name}.observed'

    @property
    def open_type(self):
        return f'saved.{self.name}.open'

    @property
    def source_keys(self):
        return _SOURCE | {'native_session_digest'} if self.native_session_digest else _SOURCE

    def decode_probe(self, raw: bytes) -> dict:
        if type(raw) is not bytes:
            raise ValueError('Saved context frames require UTF-8 bytes.')
        if len(raw) > MAX_SAVED_CODEX_FRAME_BYTES:
            raise CoreError('CAPACITY_EXCEEDED', f'saved_{self.name}_decode')
        try:
            frame = strict_json(raw.decode('utf-8'))
            canonical_json(frame)
            if (type(frame) is not dict or frame.get('contract_revision') != self.link_revision
                    or not all(_identifier(frame.get(key)) for key in _IDENTIFIERS)
                    or not _generation(frame.get('connection_generation'))):
                raise ValueError('Invalid saved context channel.')
            if frame['type'] == self.probe_type:
                if frame.keys() != _CHANNEL | {'scope', 'source'}:
                    raise ValueError('Invalid saved context probe.')
                scope, source = native_action_scope(frame['scope']), frame['source']
                if (type(source) is not dict or source.keys() != self.source_keys
                        or any(scope[key] != frame[key] for key in ('server_id', 'executor_id'))
                        or not all(_identifier(source[key]) for key in _SOURCE_IDS)
                        or not _digest(source['resource_release_digest'])
                        or (self.native_session_digest and not _digest(source['native_session_digest']))
                        or source['opening_operation_id'] == source['close_operation_id']
                        or not _generation(source['source_connection_generation'])
                        or source['source_connection_generation'] > frame['connection_generation']
                        or (source['source_connection_generation'] == frame['connection_generation']
                            and source['source_connection_id'] != frame['connection_id'])):
                    raise ValueError('Invalid retired source.')
            elif (frame['type'] != self.observed_type or frame.keys() != _CHANNEL | {'request_hash', 'available'}
                    or not _digest(frame['request_hash']) or type(frame['available']) is not bool):
                raise ValueError('Invalid saved context response.')
            return frame
        except (KeyError, UnicodeError, ValueError, TypeError, RecursionError) as error:
            raise CoreError('VALIDATION_ERROR', f'saved_{self.name}_decode', retry_safe=True) from error

    def encode_probe(self, frame: dict) -> bytes:
        _preflight_encode(frame, MAX_SAVED_CODEX_FRAME_BYTES)
        try:
            raw = canonical_json(frame)
        except (UnicodeError, ValueError, TypeError, RecursionError) as error:
            raise CoreError('VALIDATION_ERROR', f'saved_{self.name}_encode', retry_safe=True) from error
        self.decode_probe(raw)
        return raw

    def result(self, probe: dict, *, available: bool) -> dict:
        """Return only availability, scoped to the probe's exact canonical bytes."""
        raw = self.encode_probe(probe)
        if probe['type'] != self.probe_type or type(available) is not bool:
            raise CoreError('VALIDATION_ERROR', f'saved_{self.name}_result', retry_safe=True)
        result = {key: probe[key] for key in _CHANNEL}
        return dict(result, type=self.observed_type, available=available,
                    request_hash='sha256:' + sha256(raw).hexdigest())

    def operation_id(self, successor_scope, intent_hash, source_scope, source):
        """Bind the durable operation identity to the exact origin and successor."""
        body = dict(revision=self.open_revision, successor=native_action_scope(successor_scope),
                    intent_hash=intent_hash, source_scope=native_action_scope(source_scope), source=source)
        return self.operation_prefix + sha256(canonical_json(body)).hexdigest()[:48]

    def decode_open(self, raw: bytes) -> dict:
        if type(raw) is not bytes:
            raise ValueError('Saved context openings require UTF-8 bytes.')
        if len(raw) > MAX_SAVED_CODEX_OPEN_BYTES:
            raise CoreError('CAPACITY_EXCEEDED', f'saved_{self.name}_open')
        try:
            frame = strict_json(raw.decode('utf-8'))
            keys = {'contract_revision', 'type', 'operation', 'source_scope', 'source'}
            if (type(frame) is not dict or frame.keys() != keys
                    or frame['contract_revision'] != self.open_revision or frame['type'] != self.open_type):
                raise ValueError('Invalid saved context opening.')
            operation = decode_r4_frame(canonical_json(frame['operation']))
            source_scope = native_action_scope(frame['source_scope'])
            target_scope = native_action_scope({key: operation[key] for key in source_scope})
            if (operation['type'] != 'operation.submit' or operation['action'] != 'runtime.open'
                    or operation['payload']['adapter_id'] != self.adapter_id or operation['payload']['mode'] != 'managed'
                    or source_scope['session_id'] == target_scope['session_id']
                    or any(target_scope[key] != value for key, value in source_scope.items()
                           if key not in ('session_id', 'session_owner_generation'))):
                raise ValueError('The saved context belongs to a different authority.')
            probe = {key: operation[key] for key in (*_IDENTIFIERS[:3], 'connection_generation')}
            self.encode_probe(dict(probe, contract_revision=self.link_revision, type=self.probe_type,
                request_id=operation['operation_id'], scope=source_scope, source=frame['source']))
            expected_id = self.operation_id(target_scope, operation['intent_hash'], source_scope, frame['source'])
            if operation['operation_id'] != expected_id:
                raise ValueError('The opening identity does not bind the saved source.')
            return frame
        except (KeyError, UnicodeError, ValueError, TypeError, RecursionError) as error:
            raise CoreError('VALIDATION_ERROR', f'saved_{self.name}_open', retry_safe=True) from error

    def encode_open(self, operation, *, source_scope, source):
        frame = dict(contract_revision=self.open_revision, type=self.open_type,
                     operation=operation, source_scope=source_scope, source=source)
        _preflight_encode(frame, MAX_SAVED_CODEX_OPEN_BYTES)
        raw = canonical_json(frame)
        self.decode_open(raw)
        return raw


CODEX_SAVED_CONTEXT = SavedContextCodec('codex_app_server', 'codex', 'savedop_')
CLAUDE_SAVED_CONTEXT = SavedContextCodec('claude_stream', 'claude', 'savedclaudeop_', native_session_digest=True)
PI_SAVED_CONTEXT = SavedContextCodec('pi_rpc', 'pi', 'savedpiop_', native_session_digest=True)
SAVED_CONTEXT_CODECS = (CODEX_SAVED_CONTEXT, CLAUDE_SAVED_CONTEXT, PI_SAVED_CONTEXT)

# Keep the existing Codex imports and its negotiated wire format stable.
SAVED_CODEX_LINK_REVISION = CODEX_SAVED_CONTEXT.link_revision
SAVED_CODEX_PROBE = CODEX_SAVED_CONTEXT.probe_type
SAVED_CODEX_OBSERVED = CODEX_SAVED_CONTEXT.observed_type
SAVED_CODEX_OPEN_REVISION = CODEX_SAVED_CONTEXT.open_revision
SAVED_CODEX_OPEN = CODEX_SAVED_CONTEXT.open_type
SAVED_CODEX_OPERATION_PREFIX = CODEX_SAVED_CONTEXT.operation_prefix
decode_saved_codex_frame = CODEX_SAVED_CONTEXT.decode_probe
encode_saved_codex_frame = CODEX_SAVED_CONTEXT.encode_probe
saved_codex_result = CODEX_SAVED_CONTEXT.result
saved_codex_operation_id = CODEX_SAVED_CONTEXT.operation_id
decode_saved_codex_open = CODEX_SAVED_CONTEXT.decode_open
encode_saved_codex_open = CODEX_SAVED_CONTEXT.encode_open


def saved_native_session_digest(native_session_id: str) -> str:
    return 'sha256:' + sha256(canonical_json(native_session_id)).hexdigest()
