"""Single source of truth for external Nexus identifier policy (C1/PC05).

The bundled NXL schemas fix external IDs as non-empty strings of at most
160 characters (`contracts/generate.py` ``ID``). This module is the Python
consumer of the same policy: exact-string equality, no coercion, no
truncation, no normalization, no silent hashing. Legacy development
journals may hold IDs up to 256 characters; those remain readable through
the bounded legacy query, but no new long ID is admitted.
"""

from __future__ import annotations

from .models import CoreError

NEXUS_ID_MAX_LENGTH = 160
NEXUS_LEGACY_ID_MAX_LENGTH = 256
_RESERVED_PREFIX = "core.internal."


def validate_external_id(operation_id: object, *, stage: str = "admission",
                         field: str = "operation_id") -> str:
    if type(operation_id) is not str or not operation_id:
        raise CoreError("OPERATION_INVALID", stage,
                        retry_safe=True)
    if len(operation_id) > NEXUS_ID_MAX_LENGTH:
        raise CoreError("OPERATION_INVALID", stage,
                        retry_safe=True)
    if operation_id.startswith(_RESERVED_PREFIX):
        raise CoreError("OPERATION_INVALID", stage,
                        retry_safe=True)
    return operation_id


def validate_external_session_id(session_id: object, *,
                                 stage: str = "admission") -> str:
    if type(session_id) is not str or not session_id or (
            len(session_id) > NEXUS_ID_MAX_LENGTH):
        raise CoreError("OPERATION_INVALID", stage,
                        retry_safe=True)
    return session_id


def validate_legacy_id(operation_id: object, *, stage: str = "legacy_query",
                       field: str = "legacy_operation_id") -> str:
    if (type(operation_id) is not str or not operation_id or
            len(operation_id) > NEXUS_LEGACY_ID_MAX_LENGTH):
        raise CoreError("OPERATION_INVALID", stage,
                        retry_safe=True)
    return operation_id
