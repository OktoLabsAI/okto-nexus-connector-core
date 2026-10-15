"""Lossless, bounded batching for live native subscribers.

Replay history retains the original events. Only adjacent compatible deltas
are combined, before the bridge normalizes and persists them. Lifecycle,
approval, snapshot and tool boundary events are never combined.
"""
from dataclasses import fields, replace
import json


def _compatible(first, last):
    return (not first.output_snapshot and not last.output_snapshot
            and all(getattr(first, field.name) == getattr(last, field.name)
                    for field in fields(first)
                    if field.name not in {'payload', 'occurred_at'})
            and first.kind in {'output_delta', 'tool_activity'})


def _merge(first, last, key):
    if (not isinstance(first.get(key), str) or not isinstance(last.get(key), str)
            or {k: v for k, v in first.items() if k != key}
            != {k: v for k, v in last.items() if k != key}):
        return None
    return dict(last, **{key: first[key] + last[key]})


def _bounded(event, payload):
    # Text is duplicated as output_text by the bridge; leave envelope room
    # below the public 64 KiB event limit, including multibyte characters.
    if payload is not None and len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) <= 24 * 1024:
        return replace(event, payload=payload)
    return None


def coalesce_claude_delta(first, last):
    if (not _compatible(first, last)
            or first.native_event != 'stream_event:content_block_delta'):
        return None
    if first.kind == 'output_delta':
        return _bounded(last, _merge(first.payload, last.payload, 'text'))
    # Thinking and tool-input fragments retain their native block/type and
    # enclosing metadata. They must never become assistant reply text.
    a, b = first.payload.get('event'), last.payload.get('event')
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    da, db = a.get('delta'), b.get('delta')
    if not isinstance(da, dict) or not isinstance(db, dict):
        return None
    key = {'thinking_delta': 'thinking', 'input_json_delta': 'partial_json',
           'signature_delta': 'signature'}.get(da.get('type'))
    if key is None:
        return None
    delta = _merge(da, db, key)
    if (delta is None or {k: v for k, v in a.items() if k != 'delta'} !=
            {k: v for k, v in b.items() if k != 'delta'} or
            {k: v for k, v in first.payload.items() if k != 'event'} !=
            {k: v for k, v in last.payload.items() if k != 'event'}):
        return None
    return _bounded(last, dict(last.payload, event=dict(b, delta=delta)))


def coalesce_codex_delta(first, last):
    if (not _compatible(first, last) or first.native_event not in {
            'item/agentMessage/delta', 'item/reasoning/summaryTextDelta',
            'item/reasoning/textDelta', 'item/plan/delta'}):
        return None
    # Includes exact thread/turn/item and reasoning index equality.
    return _bounded(last, _merge(first.payload, last.payload, 'delta'))
