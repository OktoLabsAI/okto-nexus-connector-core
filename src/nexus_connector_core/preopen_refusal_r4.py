"""Positive journal fencing for an opening interrupted before Core admission.

Only a trusted host recovering under an authenticated replacement connection
may prepare this association. Persist it before invoking the journal. Its
digest detects corruption, not authenticity. It does not attest resource
release, authorize a lease, claim a session, or decide a business outcome.
"""
from hashlib import sha256

from .models import CoreError, OperationKey, OperationReceipt
from .ports import Journal
from .protocol import canonical_json, strict_json
from .receipt_binding_r4 import validate_r4_receipt_binding

PREOPEN_REFUSAL_REVISION = 'nexus-preopen-refusal-v1'


def _digest(value):
    return 'sha256:' + sha256(canonical_json(value)).hexdigest()


def _association(source, session_owner_generation, recovery, prior_binding):
    return dict(schema_version=1, source=source,
                session_owner_generation=session_owner_generation,
                recovery=recovery, prior_binding=prior_binding)


def _binding(association):
    body = dict(schema_version=1, source=association['source'], action='runtime.open',
                core_intent_hash=_digest(dict(domain='nexus-r4-preopen-refusal-v1',
                                             association=association)))
    return validate_r4_receipt_binding(dict(body, digest=_digest(body)))


def prepare_r4_preopen_refusal(source, *, session_owner_generation, recovery, prior_binding=None):
    """Bind original non-secret provenance to a strictly newer control owner.

    No absence lookup is trusted here: persist_r4_preopen_refusal must win the
    journal admission CAS against any delayed original execution. An existing
    original intent, even RECEIVED_DURABLE, is a conflict requiring its own
    recovery. Keeping the prior projection association makes replacement
    auditable after a crash between binding and runtime.open.
    """
    try:
        association = _association(source, session_owner_generation, recovery, prior_binding)
        return validate_r4_preopen_refusal(dict(association, binding=_binding(association)))
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_preopen_refusal') from error


def validate_r4_preopen_refusal(value):
    """Validate a detached durable association, never an execution request."""
    try:
        value = strict_json(canonical_json(value).decode())
        if (type(value) is not dict or set(value) != {
                'schema_version', 'source', 'session_owner_generation', 'recovery', 'prior_binding', 'binding'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1):
            raise ValueError('Invalid preopening refusal association.')
        binding = validate_r4_receipt_binding(value['binding'])
        source, recovery, generation = value['source'], value['recovery'], value['session_owner_generation']
        if (binding['source'] != source or type(generation) is not int or not 1 <= generation <= 9223372036854775807
                or type(recovery) is not dict or set(recovery) != {'connection_id', 'connection_generation'}
                or type(recovery['connection_id']) is not str or not 1 <= len(recovery['connection_id']) <= 160
                or recovery['connection_id'] == source['connection_id']
                or type(recovery['connection_generation']) is not int
                or not source['connection_generation'] < recovery['connection_generation'] <= 9223372036854775807):
            raise CoreError('STALE_GENERATION', 'r4_preopen_refusal')
        prior = value['prior_binding']
        if prior is not None:
            prior = validate_r4_receipt_binding(prior)
            if prior['action'] != 'runtime.open' or prior['source'] != source:
                raise CoreError('SCOPE_MISMATCH', 'r4_preopen_refusal')
        association = _association(source, generation, recovery, prior)
        if binding != _binding(association):
            raise CoreError('SCOPE_MISMATCH', 'r4_preopen_refusal')
        return value
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_preopen_refusal') from error


async def persist_r4_preopen_refusal(journal: Journal, refusal):
    """Atomically exclude the original opening or preserve its existing fact.

    Domain separation means an old consumer cannot admit its original intent
    after this admission commits. A crash before the final receipt can finish
    this same refusal. Normal quota is used; containment capacity is reserved.
    Physical slot release is a separate host obligation.
    """
    value = validate_r4_preopen_refusal(refusal)
    binding, source = value['binding'], value['source']
    key = OperationKey(source['server_id'], source['executor_id'], source['operation_id'])
    old, _ = await journal.admit(key, binding['core_intent_hash'], source['session_id'])
    receipt = OperationReceipt(source['operation_id'], binding['core_intent_hash'], 'FAILED',
        False, True, source['session_id'], error_code='PRE_EXECUTION_FENCED')
    if old == receipt:
        return old
    if old.stage != 'RECEIVED_DURABLE' or old.possible_effect or old.native_id is not None:
        raise CoreError('OPERATION_CONFLICT', 'r4_preopen_refusal', possible_effect=True,
                        operation_id=key.operation_id)
    return await journal.record_receipt(key, receipt)


def validate_r4_preopen_report(value):
    """Validate host evidence; the authenticated Server correlates admission.

    A terminal receipt is not resource-release evidence. The host must also
    observe no session claim and confirm release of its exact physical slot.
    These are trusted executor facts, not a proof supplied by a model/tool.
    """
    from .capacity import CapacityReservation
    from .receipt_binding_r4 import project_r4_bound_receipt
    try:
        value = strict_json(canonical_json(value).decode())
        if type(value) is not dict or set(value) != {'refusal', 'receipt', 'capacity', 'slot'}:
            raise ValueError('Invalid preopening recovery report.')
        refusal = validate_r4_preopen_refusal(value['refusal'])
        source, binding = refusal['source'], refusal['binding']
        key = OperationKey(source['server_id'], source['executor_id'], source['operation_id'])
        receipt = OperationReceipt(key.operation_id, binding['core_intent_hash'], 'FAILED',
            False, True, source['session_id'], error_code='PRE_EXECUTION_FENCED')
        if value['receipt'] != project_r4_bound_receipt(binding, receipt, key=key, receipt_revision=1):
            raise CoreError('SCOPE_MISMATCH', 'r4_preopen_report')
        slot_operations = {key.operation_id}
        if value['capacity'] is not None:
            capacity = CapacityReservation.from_dict(value['capacity'])
            scope, consumption = capacity.request.scope, capacity.consumption
            if (capacity.state != 'RELEASED' or capacity.request.unit != 'new_session' or consumption is None
                    or any(getattr(scope, k) != source[k] for k in ('server_id', 'executor_id', 'binding_id',
                        'agent_id', 'session_id', 'connection_generation'))
                    or scope.session_owner_generation != refusal['session_owner_generation']
                    or consumption.opening_operation_id != key.operation_id
                    or consumption.opening_intent_hash != source['intent_hash']):
                raise CoreError('SCOPE_MISMATCH', 'r4_preopen_report')
            slot_operations.add('capacity:' + capacity.reservation_id)
        slot = value['slot']
        if slot is not None and (type(slot) is not dict or set(slot) != {
                'server_id', 'executor_id', 'session_id', 'opening_operation_id', 'released'}
                or any(slot[k] != source[k] for k in ('server_id', 'executor_id', 'session_id'))
                or slot['released'] is not True or slot['opening_operation_id'] not in slot_operations):
            raise CoreError('SCOPE_MISMATCH', 'r4_preopen_report')
        if value['capacity'] is not None and slot is None:
            raise CoreError('SCOPE_MISMATCH', 'r4_preopen_report')
        return value
    except (KeyError, TypeError, ValueError, RecursionError, AttributeError) as error:
        raise CoreError('VALIDATION_ERROR', 'r4_preopen_report') from error
