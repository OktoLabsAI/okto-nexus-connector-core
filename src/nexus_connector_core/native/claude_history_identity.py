"""Bound identity facts for an observed Claude stream-json conversation."""

from uuid import UUID


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
