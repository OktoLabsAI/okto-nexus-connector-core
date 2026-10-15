"""Technical request/result mapping shared by authenticated capacity adapters.

No socket, handoff policy, credential, native launch or second execution intent
belongs here. The facade revalidates the host authority on every operation.
"""
from .capacity import (CAPACITY_CONTRACT_REVISION, CAPACITY_REASONS,
                       CapacityRequest, CapacityConsumption, CapacityAssessment,
                       CapacityReservation)
from .capacity_codec import CAPACITY_REQUEST_TYPES, encode_capacity_frame, decode_capacity_frame
from .models import CoreError
from .ports import RuntimeCapacity


def capacity_result_frame(frame, result):
    if result is None:
        if frame['type'] != 'capacity.get':
            raise ValueError('Only a reservation lookup can return not_found.')
        kind = 'not_found'
    elif type(result) is CapacityAssessment:
        kind = 'assessment'
    elif type(result) is CapacityReservation:
        kind = 'reservation'
    else:
        raise ValueError('Invalid capacity result.')
    request = CapacityRequest.from_dict(frame['request'])
    response = {key: frame[key] for key in ('contract_revision', 'server_id', 'executor_id',
                                           'connection_id', 'connection_generation', 'request_id')}
    response.update(type='capacity.result', request_hash=request.request_hash,
                    result_type=kind, result=result.to_dict() if result is not None else None)
    # Prevent an implementation error from publishing another attempt's result.
    encode_capacity_frame(response)
    return response


def capacity_denial_frame(frame, reason):
    request = CapacityRequest.from_dict(frame['request'])
    return capacity_result_frame(frame, CapacityAssessment(
        CAPACITY_CONTRACT_REVISION, request.request_hash, reason, 0, 0))


async def execute_capacity_control(service: RuntimeCapacity, frame):
    frame = decode_capacity_frame(encode_capacity_frame(frame))
    kind = frame['type']
    if kind not in CAPACITY_REQUEST_TYPES:
        raise ValueError('Expected a capacity request.')
    request = CapacityRequest.from_dict(frame['request'])
    try:
        if kind == 'capacity.assess':
            result = await service.assess_capacity(request)
        elif kind == 'capacity.reserve':
            result = await service.try_reserve_capacity(request)
        elif kind == 'capacity.get':
            result = await service.get_capacity_reservation(request)
        elif kind == 'capacity.consume':
            result = await service.consume_capacity(request, frame['reservation_id'],
                CapacityConsumption.from_dict(frame['consumption']))
        else:
            result = await service.release_capacity(request, frame['reservation_id'], frame['reason'])
    except CoreError as error:
        # A failed/uncertain storage commit must never become a safe refusal.
        reason = error.code if error.code in CAPACITY_REASONS and not error.possible_effect else 'NEEDS_RECONCILIATION'
        return capacity_denial_frame(frame, reason)
    return capacity_result_frame(frame, result)
