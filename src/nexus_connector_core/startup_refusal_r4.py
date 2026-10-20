"""Fence an opening that its current host stopped before native admission.

The trusted host must persist this association and quiesce the original
producer before using it. The journal CAS is the no-admission proof; an
exception's flags or an absent receipt are not. Resource release is a separate
obligation and must be proved before advertising reusable capacity.
"""
from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .models import CoreError
from .native_action_bridge import native_action_scope
from .operation_refusal_r4 import _SOURCE, _SCOPE, _digest, _persist_refusal
from .protocol import canonical_json, strict_json
from .receipt_binding_r4 import validate_r4_receipt_binding


def _binding(source, scope, grant_id):
    body = dict(schema_version=1, source=source, action='runtime.open',
        core_intent_hash=_digest(dict(domain='nexus-r4-startup-refusal-v1',
                                     source=source, scope=scope, grant_id=grant_id)))
    return validate_r4_receipt_binding(dict(body, digest=_digest(body)))


def prepare_r4_startup_refusal(submit):
    """Preserve exact admission provenance without provider payload or secrets."""
    frame = decode_r4_frame(encode_r4_frame(submit))
    if frame['type'] != 'operation.submit' or frame['action'] != 'runtime.open':
        raise CoreError('VALIDATION_ERROR', 'r4_startup_refusal')
    scope = {key: frame[key] for key in _SCOPE}
    source = {key: frame[key] for key in _SOURCE}
    return validate_r4_startup_refusal(dict(schema_version=1, kind='startup_failure',
        scope=scope, grant_id=frame['grant_id'], binding=_binding(source, scope, frame['grant_id'])))


def validate_r4_startup_refusal(value):
    try:
        value = strict_json(canonical_json(value).decode())
        if (type(value) is not dict or set(value) != {'schema_version', 'kind', 'scope', 'grant_id', 'binding'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['kind'] != 'startup_failure' or type(value['grant_id']) is not str
                or not 1 <= len(value['grant_id']) <= 160):
            raise ValueError('Invalid startup refusal association.')
        scope = native_action_scope(value['scope'])
        binding = validate_r4_receipt_binding(value['binding'])
        source = binding['source']
        if (binding['action'] != 'runtime.open'
                or any(source[key] != scope[key] for key in ('server_id', 'executor_id', 'binding_id', 'agent_id', 'session_id'))
                or binding != _binding(source, scope, value['grant_id'])):
            raise CoreError('SCOPE_MISMATCH', 'r4_startup_refusal')
        return value
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_startup_refusal') from error


async def persist_r4_startup_refusal(journal, refusal):
    """Finish this refusal or preserve a conflicting original native intent.

    No replacement connection, lease denial, native session claim or process
    exit is invented. The original operation ID cannot later admit a different
    intent, even if the original producer's delayed observation resumes.
    """
    value = validate_r4_startup_refusal(refusal)
    return await _persist_refusal(journal, value['binding'], 'PREPARATION_FAILED')
