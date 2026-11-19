"""Bound identity facts for an observed Claude stream-json conversation."""

from dataclasses import replace
from uuid import UUID

from ..event_artifacts import MAX_PAYLOAD_BYTES
from ..protocol import canonical_json


CLAUDE_HISTORY_IDENTITY = 'claude_history_identity'


def claude_session_uuid(value: object) -> str | None:
    """Accept only the exact canonical UUID reported by Claude."""
    if type(value) is not str or len(value) != 36:
        return None
    try:
        return value if str(UUID(value)) == value else None
    except ValueError:
        return None


def confirmed_claude_history(value) -> str | None:
    if (type(value) is not dict or value.keys() != {'schema_version', 'session_id'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1):
        return None
    return claude_session_uuid(value['session_id'])


def project_claude_history(event, fact, clean):
    """Attach corroboration only if it fits on the otherwise valid event."""
    session_uuid = confirmed_claude_history(fact)
    if session_uuid is None or clean(fact) != fact or event.payload.get('session_id') != session_uuid:
        return event
    payload = {**event.payload, CLAUDE_HISTORY_IDENTITY: fact}
    if len(canonical_json(payload)) > MAX_PAYLOAD_BYTES:
        return event
    return replace(event, payload=payload)
