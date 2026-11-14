"""Pure bounded restart decisions; hosts own all processes, receipts and effects.

The monotonic deadline belongs to one live supervisor. A persisted state never
authorizes a replacement supervisor to infer child death or resume a launch.
An observed child exit says nothing about its descendants or work claims.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class RestartPolicy:
    max_restarts: int = 3
    backoff_seconds: float = 60.0

    def __post_init__(self):
        if type(self.max_restarts) is not int or not 0 <= self.max_restarts <= 100:
            raise ValueError('Invalid restart limit')
        _time(self.backoff_seconds)
        if self.backoff_seconds < 0:
            raise ValueError('Invalid restart delay')


@dataclass(frozen=True)
class RetryState:
    attempts_started: int = 0
    phase: str = 'initial'
    next_retry_monotonic: float | None = None
    last_exit_code: int | None = None

    def __post_init__(self):
        if type(self.attempts_started) is not int or self.attempts_started < 0:
            raise ValueError('Invalid attempt count')
        if self.phase not in {'initial', 'running', 'backoff', 'exhausted', 'stopped', 'unknown'}:
            raise ValueError('Invalid supervisor phase')
        if self.next_retry_monotonic is not None:
            _time(self.next_retry_monotonic)
        if (self.phase == 'backoff') != (self.next_retry_monotonic is not None):
            raise ValueError('Backoff requires exactly one monotonic deadline')
        if self.phase == 'initial' and self.attempts_started != 0:
            raise ValueError('Initial state cannot erase prior attempts')
        if self.phase in {'running', 'backoff', 'exhausted'} and self.attempts_started == 0:
            raise ValueError('Active state requires an attempt reservation')
        if self.last_exit_code is not None and type(self.last_exit_code) is not int:
            raise ValueError('Invalid child exit code')


def _time(value):
    if type(value) not in {float, int} or not math.isfinite(value):
        raise ValueError('A finite monotonic time is required')


def reserve_attempt(state: RetryState, now: float, desired_running: bool,
                    *, policy: RestartPolicy = RestartPolicy()) -> RetryState:
    """Reserve durably before one spawn; READY/connect never reset the budget."""
    _time(now)
    if type(desired_running) is not bool:
        raise ValueError('Explicit desired-running state is required')
    if state.phase == 'unknown':
        return state
    if not desired_running:
        return replace(state, phase='stopped', next_retry_monotonic=None)
    if state.phase not in {'initial', 'backoff'}:
        raise ValueError('This state cannot select another child')
    if state.attempts_started >= policy.max_restarts + 1:
        return replace(state, phase='exhausted', next_retry_monotonic=None)
    if state.phase == 'backoff' and now < state.next_retry_monotonic:
        return state
    return replace(state, attempts_started=state.attempts_started + 1,
                   phase='running', next_retry_monotonic=None)


def record_exit(state: RetryState, now: float, exit_code: int, desired_running: bool,
                *, policy: RestartPolicy = RestartPolicy()) -> RetryState:
    """Caller must prove exit of its retained exact child handle first.

    Even exit zero is unexpected if the canonical stop latch remains running.
    No work replay, descendant cleanup or claim release follows from this rule.
    """
    _time(now)
    if type(exit_code) is not int or type(desired_running) is not bool:
        raise ValueError('Explicit child exit and desired state are required')
    if state.phase != 'running':
        raise ValueError('No owned running attempt can be completed')
    if not desired_running:
        return replace(state, phase='stopped', last_exit_code=exit_code)
    if state.attempts_started >= policy.max_restarts + 1:
        return replace(state, phase='exhausted', last_exit_code=exit_code)
    return replace(state, phase='backoff', last_exit_code=exit_code,
                   next_retry_monotonic=now + policy.backoff_seconds)
