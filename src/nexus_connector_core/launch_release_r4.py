"""Authenticated recovery of a fenced opening whose producer never ran.

The original receipt stays monotonic. This independent proof does not claim a
process exited or authorize a command replay. Hosts remain responsible for
current authority, durable publication and physical slot accounting.
"""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files

from jsonschema import Draft202012Validator

from .models import ClaimedSession, CoreError, OperationKey, SessionKey
from .process_launch import ProcessLaunchIdentity, ProcessLaunchRecord, validate_launch_identity
from .protocol import canonical_json, strict_json
from .receipt_binding_r4 import project_r4_bound_receipt, validate_r4_receipt_binding

LAUNCH_RECOVERY_REVISION = 'nexus-launch-recovery-v1'


@lru_cache(maxsize=1)
def _proof_schema():
    from .frame_codec_r4 import R4_CONTRACT_REVISION, verify_r4_bundle
    verify_r4_bundle()
    folder = files('nexus_connector_core').joinpath('contracts', 'launch_recovery', 'v1')
    raw = folder.joinpath('proof.schema.json').read_bytes()
    manifest = strict_json(folder.joinpath('manifest.json').read_text(encoding='utf-8'))
    if manifest != dict(revision=LAUNCH_RECOVERY_REVISION, base_revision=R4_CONTRACT_REVISION,
            status='executable', sha256={'proof.schema.json': sha256(raw).hexdigest()}):
        raise CoreError('CONTRACT_BUNDLE_INVALID', 'launch_recovery_bundle')
    schema = strict_json(raw.decode('utf-8'))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=2)
def launch_recovery_schema_validator(preopen=False):
    """Compose the named extension without rewriting historical R4 bytes."""
    if preopen:
        from .preopen_bundle_r4 import preopen_schema_validator
        schema = deepcopy(preopen_schema_validator().schema)
    else:
        from .frame_codec_r4 import _resources
        schema = deepcopy(_resources()[0].schema)
    for branch in schema['oneOf']:
        kind = branch['properties']['type']['const']
        if kind not in ('reconcile.request', 'reconcile.report'):
            continue
        branch['properties']['launch_recovery_supported'] = {'const': True}
        branch['required'].append('launch_recovery_supported')
        if kind == 'reconcile.report':
            fact = branch['properties']['ownership_facts']['items']
            fact['properties']['process_state']['enum'].append('NOT_STARTED')
            fact['properties']['launch_proof'] = _proof_schema()
            fact['allOf'] = [dict(
                **{'if': {'properties': {'process_state': {'const': 'NOT_STARTED'}}}},
                then={'required': ['launch_proof', 'proof_digest']},
                **{'else': {'not': {'required': ['launch_proof']}}})]
    return Draft202012Validator(schema)


def decode_unstarted_proof(value):
    try:
        Draft202012Validator(_proof_schema()).validate(value)
        identity = value['identity']
        launch = ProcessLaunchRecord(ProcessLaunchIdentity(
            key=SessionKey(**identity['key']),
            **{k: v for k, v in identity.items() if k != 'key'}),
            **{k: v for k, v in value.items() if k != 'identity'})
        validate_launch_identity(launch.identity)
        return launch
    except (ValueError, TypeError, KeyError) as error:
        raise CoreError('VALIDATION_ERROR', 'launch_recovery_proof') from error
    except Exception as error:
        from jsonschema.exceptions import ValidationError
        if not isinstance(error, ValidationError):
            raise
        raise CoreError('VALIDATION_ERROR', 'launch_recovery_proof') from error


def unstarted_release_digest(proof, opening_intent_hash):
    import re
    decode_unstarted_proof(proof)
    if type(opening_intent_hash) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', opening_intent_hash):
        raise CoreError('VALIDATION_ERROR', 'launch_recovery_proof')
    return 'sha256:' + sha256(canonical_json(dict(kind=LAUNCH_RECOVERY_REVISION,
        proof=proof, opening_intent_hash=opening_intent_hash))).hexdigest()


def validate_unstarted_release(fact, opening, *, connection_generation):
    """Validate an authenticated host fact against the canonical opening."""
    launch = decode_unstarted_proof(fact['launch_proof'])
    identity = launch.identity
    if (fact['process_state'] != 'NOT_STARTED' or opening['stage'] != 'FAILED'
            or opening.get('native_id') is not None
            or any(opening[k] != getattr(identity.key, k) for k in ('server_id', 'executor_id', 'session_id'))
            or opening['operation_id'] != identity.opening_operation_id
            or opening['connection_generation'] != identity.connection_generation
            or fact['session_id'] != identity.key.session_id
            or fact['owner_generation'] != identity.owner_generation
            or type(connection_generation) is not int or connection_generation <= identity.connection_generation
            or fact['proof_digest'] != unstarted_release_digest(fact['launch_proof'], opening['intent_hash'])):
        raise CoreError('SCOPE_MISMATCH', 'launch_recovery_proof')
    return launch


def project_r4_unstarted_release(binding, claim, slot, receipt, launch, *, journal_slot, birth):
    binding = validate_r4_receipt_binding(binding)
    if not isinstance(claim, ClaimedSession) or not isinstance(launch, ProcessLaunchRecord):
        raise CoreError('SCOPE_MISMATCH', 'launch_recovery_proof')
    proof = asdict(launch)
    decode_unstarted_proof(proof)
    identity = launch.identity
    if (binding['action'] != 'runtime.open' or identity.key != claim.key
            or identity.opening_operation_id != claim.opening_operation_id
            or identity.owner_generation != claim.opening_owner_generation
            or identity.connection_generation != claim.opening_connection_generation
            or birth is not None or any(resource is not None and (
                resource.key != claim.key or resource.opening_operation_id != claim.opening_operation_id
                or resource.released is not True) for resource in (slot, journal_slot))):
        raise CoreError('RECONCILIATION_REQUIRED', 'launch_recovery_proof')
    key = OperationKey(claim.key.server_id, claim.key.executor_id, claim.opening_operation_id)
    opening = project_r4_bound_receipt(binding, receipt, key=key, receipt_revision=1)
    fact = dict(session_id=claim.key.session_id, owner_generation=claim.opening_owner_generation,
        process_state='NOT_STARTED', launch_proof=proof,
        proof_digest=unstarted_release_digest(proof, opening['intent_hash']))
    validate_unstarted_release(fact, opening, connection_generation=identity.connection_generation+1)
    return fact
