"""Portable one-shot policy and caller outcome contracts.

These contracts describe resource limits, not execution authority. Hosts still
authorize every opening and every productive turn through the normal lease.
"""
from dataclasses import asdict, dataclass

from .models import CoreError


@dataclass(frozen=True, slots=True)
class OneShotPolicy:
    max_parallel: int = 1
    warm_instances: int = 0
    overflow: str = 'queue'
    queue_capacity: int = 32
    queue_timeout_seconds: int = 300
    execution_timeout_seconds: int = 1800

    def __post_init__(self):
        # Zero means no pool-specific ceiling. Hosts retain their own resource
        # budgets; this does not confer execution or allocation authority.
        bounds = {'max_parallel': (0, 256), 'warm_instances': (0, 255),
                  'queue_capacity': (0, 10000), 'queue_timeout_seconds': (1, 86400),
                  'execution_timeout_seconds': (1, 604800)}
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise CoreError('VALIDATION_ERROR', 'one_shot_policy', message=f'Invalid {name}.')
        if (self.max_parallel and self.warm_instances >= self.max_parallel) or self.overflow not in ('queue', 'reject'):
            raise CoreError('VALIDATION_ERROR', 'one_shot_policy',
                            message='Warm instances must be below parallel capacity; overflow must be queue or reject.')

    def to_dict(self):
        return asdict(self)


def validate_one_shot_policy(value):
    if type(value) is not dict or set(value) - set(OneShotPolicy.__dataclass_fields__):
        raise CoreError('VALIDATION_ERROR', 'one_shot_policy')
    return OneShotPolicy(**value)


@dataclass(frozen=True, slots=True)
class OneShotFailure:
    call_id: str
    code: str
    message: str
    stage: str
    execution_started: bool
    possible_effect: bool
    retry_safe: bool

    def __post_init__(self):
        if any(type(v) is not str or not v.strip() or len(v) > limit
               for v, limit in ((self.call_id, 160), (self.code, 100),
                                (self.message, 2048), (self.stage, 100))):
            raise CoreError('VALIDATION_ERROR', 'one_shot_failure')
        if any(type(v) is not bool for v in
               (self.execution_started, self.possible_effect, self.retry_safe)):
            raise CoreError('VALIDATION_ERROR', 'one_shot_failure')
        if self.possible_effect and self.retry_safe:
            raise CoreError('VALIDATION_ERROR', 'one_shot_failure',
                            message='An uncertain effect cannot be declared safe to replay.')

    def to_dict(self):
        return asdict(self)
