import copy

import pytest

from nexus_connector_core import CoreError, OperationKey, OperationReceipt, project_r4_bound_receipt
from nexus_connector_core.capacity import (
    CAPACITY_CONTRACT_REVISION, CapacityConsumption, CapacityRequest,
    CapacityReservation, CapacityScope,
)
from nexus_connector_core.control_codec import decode_control_frame
from nexus_connector_core.startup_refusal_link import (
    STARTUP_REFUSAL_REVISION, decode_startup_refusal, encode_startup_refusal,
    startup_refusal_accepted, startup_refusal_deferred,
)
from test_r4_startup_refusal import sample


def report(with_capacity=False):
    frame, refusal = sample()
    binding = refusal['binding']
    fact = OperationReceipt(frame['operation_id'], binding['core_intent_hash'],
                            'FAILED', False, True, frame['session_id'],
                            error_code='PREPARATION_FAILED')
    receipt = project_r4_bound_receipt(binding, fact,
        key=OperationKey(frame['server_id'], frame['executor_id'], frame['operation_id']),
        receipt_revision=1)
    capacity = None
    if with_capacity:
        scope = CapacityScope(**refusal['scope'],
            connection_generation=frame['connection_generation'], boot_id='boot-1')
        request = CapacityRequest(CAPACITY_CONTRACT_REVISION, 'attempt-1', scope,
            'new_session', 'sha256:' + 'a' * 64, 30000)
        capacity = CapacityReservation('reservation-1', request, 'RELEASED', 2, 0,
            CapacityConsumption('turn-1', 'sha256:' + 'b' * 64,
                                frame['operation_id'], frame['intent_hash'])).to_dict()
    return dict(contract_revision=STARTUP_REFUSAL_REVISION, type='startup.refuse',
                request_id='refuse-1', server_id=frame['server_id'],
                executor_id=frame['executor_id'], connection_id=frame['connection_id'],
                connection_generation=frame['connection_generation'],
                refusal=refusal, receipt=receipt,
                capacity=capacity, native_absent=True)


@pytest.mark.parametrize('with_capacity', [False, True])
def test_prelease_report_is_strict_and_negotiated(with_capacity):
    request = report(with_capacity)
    encoded = encode_startup_refusal(request)
    assert decode_startup_refusal(encoded) == request
    with pytest.raises(CoreError, match='VERSION_INCOMPATIBLE'):
        decode_control_frame(encoded)
    assert decode_control_frame(encoded,
        capabilities=(STARTUP_REFUSAL_REVISION,)) == request
    for reply in (startup_refusal_accepted(request), startup_refusal_deferred(request)):
        assert decode_control_frame(encode_startup_refusal(reply),
            capabilities=(STARTUP_REFUSAL_REVISION,)) == reply


@pytest.mark.parametrize('mutation', [
    lambda value: value.update(native_absent=False),
    lambda value: value['receipt'].update(possible_effect=True, retry_safe=False),
    lambda value: value['receipt'].update(connection_generation=999),
    lambda value: value.update(connection_generation=999),
    lambda value: value['capacity']['request']['scope'].update(session_id='other'),
    lambda value: value['capacity']['consumption'].update(opening_operation_id='other'),
    lambda value: value.update(unexpected=True),
])
def test_prelease_report_rejects_changed_provenance(mutation):
    request = copy.deepcopy(report(with_capacity=True))
    mutation(request)
    with pytest.raises(CoreError):
        encode_startup_refusal(request)
