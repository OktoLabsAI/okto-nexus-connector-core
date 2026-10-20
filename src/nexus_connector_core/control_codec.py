"""Route negotiated control extensions without changing immutable R4 frames."""
from collections.abc import Collection

from .capacity import CAPACITY_CONTRACT_REVISION
from .capacity_codec import decode_capacity_frame
from .frame_codec import MAX_FRAME_BYTES
from .frame_codec_r4 import decode_r4_frame
from .models import CoreError
from .protocol import strict_json
from .lease_denial import LEASE_DENIAL_REVISION, decode_lease_denial
from .session_release import SESSION_RELEASE_REVISION, decode_session_release
from .startup_refusal_link import STARTUP_REFUSAL_REVISION, decode_startup_refusal
from .event_artifacts import EVENT_ARTIFACT_REVISION, decode_event_artifact


def decode_control_frame(raw: bytes, *, capabilities: Collection[str] = ()) -> dict:
    """Select a strict codec; negotiation is necessary, never authorization.

    Callers must still validate the authenticated connection and current scope.
    The header is only used for routing; the chosen codec validates every byte.
    """
    if type(raw) is not bytes:
        raise ValueError('Control frames require UTF-8 bytes.')
    if len(raw) > MAX_FRAME_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'control_decode', retry_safe=True)
    try:
        header = strict_json(raw.decode('utf-8', errors='strict'))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'control_decode', retry_safe=True) from error
    if type(header) is not dict:
        raise CoreError('VALIDATION_ERROR', 'control_decode', retry_safe=True)
    if header.get('contract_revision') == EVENT_ARTIFACT_REVISION:
        if isinstance(capabilities, (str, bytes)) or EVENT_ARTIFACT_REVISION not in capabilities:
            raise CoreError('VERSION_INCOMPATIBLE', 'control_negotiation')
        return decode_event_artifact(raw)
    if header.get('contract_revision') == SESSION_RELEASE_REVISION:
        if isinstance(capabilities, (str, bytes)) or SESSION_RELEASE_REVISION not in capabilities:
            raise CoreError('VERSION_INCOMPATIBLE', 'control_negotiation')
        return decode_session_release(raw)
    if header.get('contract_revision') == STARTUP_REFUSAL_REVISION:
        if isinstance(capabilities, (str, bytes)) or STARTUP_REFUSAL_REVISION not in capabilities:
            raise CoreError('VERSION_INCOMPATIBLE', 'control_negotiation')
        return decode_startup_refusal(raw)
    if header.get('contract_revision') == LEASE_DENIAL_REVISION:
        if isinstance(capabilities, (str, bytes)) or LEASE_DENIAL_REVISION not in capabilities:
            raise CoreError('VERSION_INCOMPATIBLE', 'control_negotiation')
        return decode_lease_denial(raw)
    if header.get('contract_revision') == CAPACITY_CONTRACT_REVISION:
        if isinstance(capabilities, (str, bytes)) or CAPACITY_CONTRACT_REVISION not in capabilities:
            raise CoreError('CAPACITY_PROTOCOL_UNSUPPORTED', 'control_negotiation')
        return decode_capacity_frame(raw)
    return decode_r4_frame(raw)
