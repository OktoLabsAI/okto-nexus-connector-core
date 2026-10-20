"""Content-addressed event payloads and a bounded, negotiated transfer codec.

The journal remains the replay source. Hosts persist/verify all bytes before
publishing a reference; an artifact ACK is never an event/operation ACK.
"""
import base64
import hashlib
import re

from .models import CoreError
from .protocol import canonical_json, strict_json

EVENT_ARTIFACT_REVISION = 'nexus-event-artifacts-v1'
INLINE_EVENT_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
CHUNK_BYTES = 32 * 1024
REFERENCE_KEY = '_nexus_event_artifact'
SCOPE = ('server_id', 'executor_id', 'session_id', 'stream_epoch', 'sequence')


def reference_for(event, raw):
    digest = hashlib.sha256(raw).hexdigest()
    identity = canonical_json([*[event[k] for k in SCOPE], digest])
    return dict(artifact_id='art_event_' + hashlib.sha256(identity).hexdigest(),
                sha256=digest, size_bytes=len(raw), media_type='application/json',
                revision=EVENT_ARTIFACT_REVISION)


def externalize_event(event):
    """Return a deterministic wire event and optional private payload bytes."""
    if len(canonical_json(event)) <= INLINE_EVENT_BYTES:
        return event, None
    raw = canonical_json(event['payload'])
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise CoreError('EVENT_PAYLOAD_TOO_LARGE', 'event_artifact', possible_effect=True)
    return dict(event, payload={REFERENCE_KEY: reference_for(event, raw)}), raw


def event_reference(event):
    payload = event.get('payload', {})
    if REFERENCE_KEY not in payload:
        return None
    ref = payload[REFERENCE_KEY]
    if (set(payload) != {REFERENCE_KEY} or type(ref) is not dict or
            set(ref) != {'artifact_id', 'sha256', 'size_bytes', 'media_type', 'revision'} or
            ref['revision'] != EVENT_ARTIFACT_REVISION or ref['media_type'] != 'application/json' or
            type(ref['size_bytes']) is not int or not 1 <= ref['size_bytes'] <= MAX_PAYLOAD_BYTES or
            not isinstance(ref['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', ref['sha256']) or
            ref['artifact_id'] != 'art_event_' + hashlib.sha256(canonical_json(
                [*[event[k] for k in SCOPE], ref['sha256']])).hexdigest()):
        raise CoreError('VALIDATION_ERROR', 'event_artifact_reference')
    return ref


def hydrate_event(event, raw):
    ref = event_reference(event)
    if ref is None or reference_for(event, raw) != ref:
        raise CoreError('EVENT_CONFLICT', 'event_artifact_integrity')
    payload = strict_json(raw.decode('utf-8'))
    if type(payload) is not dict or canonical_json(payload) != raw:
        raise CoreError('VALIDATION_ERROR', 'event_artifact_payload')
    return dict(event, payload=payload)


def artifact_chunks(base, event, raw):
    hydrate_event(event, raw)
    for offset in range(0, len(raw), CHUNK_BYTES):
        yield dict(base, contract_revision=EVENT_ARTIFACT_REVISION,
                   type='event.artifact.put', event=event, offset=offset,
                   data=base64.b64encode(raw[offset:offset + CHUNK_BYTES]).decode('ascii'),
                   request_id=event_reference(event)['artifact_id'] + ':' + str(offset))


def decode_event_artifact(raw):
    try:
        if type(raw) is not bytes or len(raw) > 128 * 1024:
            raise ValueError('Invalid transfer size')
        f = strict_json(raw.decode('utf-8'))
        common = {'protocol_major','contract_revision','type','server_id','executor_id',
                  'connection_id','connection_generation','binding_id','agent_id','request_id'}
        put = f['type'] == 'event.artifact.put'
        rejected = f['type'] == 'event.artifact.rejected'
        extra = {'event','offset','data'} if put else {'artifact_id','offset'} | ({'code'} if rejected else set())
        if (f['type'] not in ('event.artifact.put','event.artifact.ack','event.artifact.rejected') or
                set(f) != common | extra or
                f['protocol_major'] != 1 or f['contract_revision'] != EVENT_ARTIFACT_REVISION or
                type(f['connection_generation']) is not int or f['connection_generation'] < 1 or
                any(type(f[k]) is not str or not 1 <= len(f[k]) <= 200 for k in
                    ('server_id','executor_id','connection_id','binding_id','agent_id','request_id'))):
            raise ValueError('Invalid transfer envelope')
        if type(f['offset']) is not int or not 0 <= f['offset'] < MAX_PAYLOAD_BYTES:
            raise ValueError('Invalid offset')
        if put:
            ref = event_reference(f['event'])
            if ref is None or any(f['event'][k] != f[k] for k in ('server_id','executor_id')):
                raise ValueError('Invalid event scope')
            from .frame_codec_r4 import decode_r4_frame, R4_CONTRACT_REVISION
            batch = {k:f[k] for k in common - {'type','contract_revision','request_id'}}
            batch.update(type='event.batch',contract_revision=R4_CONTRACT_REVISION,
                         session_id=f['event']['session_id'],stream_epoch=f['event']['stream_epoch'],events=[f['event']])
            decode_r4_frame(canonical_json(batch))
            data = base64.b64decode(f['data'], validate=True)
            if (f['offset'] % CHUNK_BYTES or len(data) != min(CHUNK_BYTES, ref['size_bytes']-f['offset']) or
                    not data or f['request_id'] != ref['artifact_id'] + ':' + str(f['offset'])):
                raise ValueError('Invalid chunk')
        elif (not re.fullmatch('art_event_[0-9a-f]{64}', f['artifact_id']) or
              f['request_id'] != f['artifact_id'] + ':' + str(f['offset'])):
            raise ValueError('Invalid acknowledgement')
        if rejected and f['code'] not in ('QUOTA_EXCEEDED','ARTIFACT_STORAGE_UNAVAILABLE'):
            raise ValueError('Invalid rejection')
        return f
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'event_artifact_codec') from error


def encode_event_artifact(frame):
    raw = canonical_json(frame)
    decode_event_artifact(raw)
    return raw


def artifact_ack(frame):
    return {**{k:v for k,v in frame.items() if k not in ('event','data')},
            'type':'event.artifact.ack', 'artifact_id':event_reference(frame['event'])['artifact_id']}
