"""Default runtime automation shared by embedded hosts and Connector daemons.

Hosts supply authority-checked reconciliation and durable delivery callbacks.
This module never retries a native operation or treats a timer as release proof.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class RuntimeAutomationPolicy:
    automatic_recovery: bool = True
    retry_delays: tuple[float, ...] = (2, 4, 8, 16, 30)
    recovery_attempts: int = 5
    message_interval: float = 1
    # Connection supervision only. A connection that stayed up this long
    # starts a fresh backoff; jitter spreads reconnects of many executors.
    stable_seconds: float = 60
    retry_jitter: float = 0

    def __post_init__(self):
        if (type(self.automatic_recovery) is not bool
                or type(self.recovery_attempts) is not int or self.recovery_attempts < 1
                or type(self.retry_jitter) not in (int, float) or not 0 <= self.retry_jitter < 1
                or not self.retry_delays
                or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0
                       for n in (*self.retry_delays, self.message_interval, self.stable_seconds))):
            raise ValueError('Invalid runtime automation policy.')

    @property
    def automatic_messages(self) -> bool:
        # Delivery still requires an enabled runtime and current host authority.
        return True

    def delay(self, failures: int) -> float:
        return self.retry_delays[min(max(0, failures - 1), len(self.retry_delays) - 1)]

    def reconnect_delay(self, failures: int, rand=random.random) -> float:
        base = self.delay(failures)
        return base * (1 + self.retry_jitter * (2 * rand() - 1)) if self.retry_jitter else base


DEFAULT_RUNTIME_AUTOMATION = RuntimeAutomationPolicy()


async def _wait(stop, delay):
    try:
        await asyncio.wait_for(stop.wait(), delay)
    except asyncio.TimeoutError:
        pass


class RuntimeAutomation:
    """One host-owned supervisor; stopping joins in-flight callbacks.

    A callback must commit readiness only after Core proofs and current host
    authority have been verified. Pending delivery must atomically revalidate
    and claim new work. Reconciliation must never resubmit previous work.
    """

    def __init__(self, policy=DEFAULT_RUNTIME_AUTOMATION):
        self.policy = policy

    async def recover(self, *, attempt, stop, enabled=None, pending=None,
                      exhausted=None, wait=None, continuous=False):
        """Retry an unsuccessful initial reconciliation with bounded backoff.

        Disabled/exhausted supervisors stay observable until stopped. Toggling
        recovery off then on explicitly opens a new retry budget. Independent
        pending deliveries can progress even while this owner is blocked.
        Hosts opting into continuous recovery keep checking at the capped
        backoff after the initial budget, without replaying native operations.
        """
        pause = wait or (lambda delay: _wait(stop, delay))
        async def is_enabled():
            return await enabled() if enabled else self.policy.automatic_recovery
        previous = await is_enabled()
        attempts = 0
        while not stop.is_set():
            await pause(self.policy.delay(attempts + 1))
            if stop.is_set():
                break
            active = await is_enabled()
            if active and not previous:
                attempts = 0
            previous = active
            if not active:
                continue
            if pending is not None:
                await pending()
            if stop.is_set():
                break
            if attempts < self.policy.recovery_attempts or continuous:
                attempts += 1
                if await attempt():
                    return True
            if attempts >= self.policy.recovery_attempts and exhausted is not None:
                await exhausted()
        return False

    async def supervise_connection(self, *, cycle, stop, failed, exhausted,
                                   wait=None, enabled=None, clock=None, rand=random.random):
        """Reconnect transport and retry reconciliation until explicitly stopped.

        ``cycle`` owns negotiation, automatic message dispatch and cleanup.
        ``failed`` records a sanitized error and returns True only for a
        reconciliation failure. Network reconnects have independent backoff.
        No submitted operation is replayed by this supervisor.
        A cycle that ran for ``stable_seconds`` before failing restarts the
        backoff, so a long-lived connection does not inherit old failures.
        """
        pause = wait or (lambda delay: _wait(stop, delay))
        now = clock or asyncio.get_running_loop().time
        delay = lambda failures: self.policy.reconnect_delay(max(failures, 1), rand)
        failures = recoveries = 0
        previous = self.policy.automatic_recovery
        while not stop.is_set():
            active = await enabled() if enabled else self.policy.automatic_recovery
            if active and not previous:
                recoveries = 0
            previous = active
            if recoveries and not active:
                await pause(delay(failures))
                continue
            started = now()
            try:
                await cycle()
                failures = recoveries = 0
            except Exception as error:
                if now() - started >= self.policy.stable_seconds:
                    failures = recoveries = 0
                failures += 1
                if await failed(error):
                    recoveries += 1
                else:
                    recoveries = 0
            if not stop.is_set():
                await pause(delay(failures))
