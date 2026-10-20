"""Retained independent observation workers, shared by embedded/remote hosts.

This is scheduling, not authority or publication. Hosts supply an async observer
that retains all of its native/thread work until return. Consumers retain the
exact batch they published; newer discoveries do not replace published selection
evidence until their own publication succeeds.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import random
import secrets
import threading
import time
from typing import Awaitable, Callable

from .catalog import get_runtime_catalog
from .executor_inventory import MAX_SNAPSHOT_CANDIDATES, build_executor_inventory_snapshot
from .inventory_observations import MAX_OBSERVATION_AGE_MS
from .models import InstallationCandidate


@dataclass(frozen=True, slots=True)
class HarnessObservationResult:
    candidates: tuple[InstallationCandidate, ...]
    # Hosts may augment passive evidence with approved version observations.
    # Preserve both sets from the SAME attempt for subsequent exact selection.
    raw_candidates: tuple[InstallationCandidate, ...] | None = None


@dataclass(frozen=True, slots=True)
class HarnessObservation:
    adapter_id: str
    state: str
    observation_age_ms: int | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class InventoryObservationBatch:
    revision: int
    assembled_at_monotonic: float
    candidates: tuple[InstallationCandidate, ...]
    raw_candidates: tuple[InstallationCandidate, ...]
    observations: tuple[HarnessObservation, ...]

    def coverage(self):
        """A detached format-3 projection; no paths or mutable worker state."""
        return {row.adapter_id: dict(state=row.state,
                observation_age_ms=row.observation_age_ms, error_code=row.error_code)
                for row in self.observations}


@dataclass(frozen=True, slots=True)
class InventoryRefreshFrontier:
    owner_token: str
    attempts: tuple[tuple[str, int], ...]


class IndependentInventoryObserver:
    """One retained worker per discoverable adapter, with no global scan round.

    All public methods other than the observer's cancellation predicate belong
    to the creating event loop. Cancellation of a wait/close observer NEVER
    cancels discovery. ``aclose`` joins every producer, even after its caller
    stops waiting. A host must call ``begin_shutdown`` before fencing publication
    and must not replace this owner until ``aclose`` has completed.
    """
    def __init__(self, observe: Callable[[str, Callable[[], bool]],
                 Awaitable[HarnessObservationResult]], *, refresh_seconds=30.0,
                 retry_seconds=1.0, max_retry_seconds=30.0, clock=time.monotonic):
        if not callable(observe) or not callable(clock):
            raise TypeError('Observation and clock callbacks are required.')
        for value in (refresh_seconds, retry_seconds, max_retry_seconds):
            if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
                raise ValueError('Observation intervals must be finite and positive.')
        if retry_seconds > max_retry_seconds:
            raise ValueError('The retry base cannot exceed its maximum.')
        self.adapters = tuple(sorted(row.adapter_id for row in get_runtime_catalog().runtimes
                                     if row.discoverable))
        if not 0 < len(self.adapters) <= MAX_SNAPSHOT_CANDIDATES:
            raise ValueError('The discoverable catalog exceeds the observation budget.')
        # One prolific/broken adapter must not overflow the shared envelope and
        # prevent publication of every sibling. Refuse its entire observation,
        # never silently truncate discovered installations into false absence.
        self.max_candidates_per_adapter = MAX_SNAPSHOT_CANDIDATES // len(self.adapters)
        self._observe, self._clock = observe, clock
        self._refresh_seconds = refresh_seconds
        self._retry_seconds, self._max_retry_seconds = retry_seconds, max_retry_seconds
        self._token = secrets.token_hex(16)
        self._stopped = threading.Event()
        self._changed = asyncio.Event()
        self._wakes = {adapter: asyncio.Event() for adapter in self.adapters}
        self._started = dict.fromkeys(self.adapters, 0)
        self._completed = dict.fromkeys(self.adapters, 0)
        self._results = {}
        self._errors = {}
        self._tasks = {}
        self._join_task = None
        self._revision = 0

    def start(self):
        if self._stopped.is_set():
            raise RuntimeError('A stopped observation owner cannot restart.')
        if not self._tasks:
            asyncio.get_running_loop()
            self._tasks = {adapter: asyncio.create_task(self._run(adapter),
                name='inventory-observe-' + adapter) for adapter in self.adapters}

    def snapshot(self):
        """Copy a consistent batch; observation cost is included in each age.

        Root snapshot transport age starts at ``assembled_at_monotonic``.
        Republishing another adapter never resets an older adapter's age.
        An excessively old observation fails closed instead of clamping its age
        and making it look fresh to a consumer with a larger TTL.
        """
        now = self._clock()
        candidates, raw, rows = [], [], []
        for adapter in self.adapters:
            if adapter in self._errors:
                rows.append(HarnessObservation(adapter, 'FAILED', None, self._errors[adapter]))
            elif adapter not in self._results:
                rows.append(HarnessObservation(adapter, 'PENDING', None, None))
            else:
                started_at, result = self._results[adapter]
                age = max(0, int((now - started_at) * 1000))
                if age > MAX_OBSERVATION_AGE_MS:
                    rows.append(HarnessObservation(adapter, 'FAILED', None, 'OBSERVATION_EXPIRED'))
                    continue
                rows.append(HarnessObservation(adapter, 'PRESENT' if result.candidates else 'ABSENT', age, None))
                candidates.extend(result.candidates)
                raw.extend(result.raw_candidates if result.raw_candidates is not None else result.candidates)
        return InventoryObservationBatch(self._revision, now, tuple(candidates), tuple(raw), tuple(rows))

    def request_refresh(self, adapter_ids=None):
        """Require a NEW attempt per selected adapter, even during an old scan.

        Requests coalesce into per-adapter frontiers, not an unbounded job list.
        A failed attempt completes its frontier with explicit FAILED evidence.
        The caller must inspect the published result, not infer success from
        completion. Frontiers cannot be reused with a replacement owner.
        """
        if self._stopped.is_set():
            raise RuntimeError('The observation owner is stopping.')
        adapters = self.adapters if adapter_ids is None else tuple(adapter_ids)
        if not adapters or len(set(adapters)) != len(adapters) or set(adapters) - set(self.adapters):
            raise ValueError('Refresh requires unique known adapters.')
        frontier = InventoryRefreshFrontier(self._token,
            tuple((adapter, self._started[adapter] + 1) for adapter in sorted(adapters)))
        for adapter in adapters:
            self._wakes[adapter].set()
        return frontier

    def refresh_complete(self, frontier):
        if (not isinstance(frontier, InventoryRefreshFrontier) or frontier.owner_token != self._token
                or not frontier.attempts or tuple(sorted(frontier.attempts)) != frontier.attempts
                or len({a for a, _ in frontier.attempts}) != len(frontier.attempts)
                or any(a not in self._completed or type(n) is not int or n <= 0 for a, n in frontier.attempts)):
            raise ValueError('Refresh frontier does not belong to this observation owner.')
        return all(self._completed[adapter] >= attempt for adapter, attempt in frontier.attempts)

    async def wait_refresh(self, frontier):
        while not self._stopped.is_set():
            self._changed.clear()
            if self.refresh_complete(frontier):
                return True
            await self._changed.wait()
        return False

    async def wait_changed(self, after_revision):
        if type(after_revision) is not int or after_revision < -1:
            raise ValueError('A nonnegative revision or initial -1 is required.')
        while not self._stopped.is_set():
            self._changed.clear()
            if self._revision > after_revision:
                return self.snapshot()
            await self._changed.wait()
        return None

    async def _run(self, adapter):
        failures = 0
        wake = self._wakes[adapter]
        while not self._stopped.is_set():
            wake.clear()
            self._started[adapter] += 1
            started_at = self._clock()
            error_code = None
            try:
                result = await self._observe(adapter, self._stopped.is_set)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise  # The host must retain/join its worker on shutdown.
                # An observer may await a separately cancelled child. That is
                # a failed attempt, not permission to silently lose this worker.
                error_code = 'DISCOVERY_CANCELLED'
            except Exception:
                # Exception messages/codes may contain paths or provider data.
                # Keep the shared observation contract strictly path-free.
                error_code = 'DISCOVERY_FAILED'
            else:
                try:
                    # Verify one adapter before accepting it into shared state.
                    # Invalid evidence cannot poison sibling publications.
                    await asyncio.to_thread(self._validate_result, adapter, result)
                except Exception:
                    error_code = 'INVALID_OBSERVATION'
            if self._stopped.is_set():
                return  # Late discovery cannot publish after the owner's fence.
            self._completed[adapter] = self._started[adapter]
            if error_code:
                self._errors[adapter] = error_code
                self._results.pop(adapter, None)
                failures += 1
                delay = min(self._max_retry_seconds,
                    self._retry_seconds * 2 ** min(failures - 1, 16) * random.uniform(.8, 1.2))
            else:
                self._errors.pop(adapter, None)
                self._results[adapter] = (started_at, result)
                failures = 0
                delay = self._refresh_seconds
            self._revision += 1
            self._changed.set()
            try:
                await asyncio.wait_for(wake.wait(), delay)
            except TimeoutError:
                pass

    def _validate_result(self, adapter, result):
        if (not isinstance(result, HarnessObservationResult)
                or type(result.candidates) is not tuple
                or result.raw_candidates is not None and type(result.raw_candidates) is not tuple
                or max(len(result.candidates), len(result.raw_candidates or ())) > self.max_candidates_per_adapter
                or any(not isinstance(item, InstallationCandidate) or item.adapter_id != adapter
                       for item in (*result.candidates, *(result.raw_candidates or ())))):
            raise ValueError('Invalid adapter observation.')
        if result.raw_candidates is not None:
            def identities(items):
                return sorted((item.executable, item.launch_script or '', item.fingerprint,
                               item.installation_ref or '') for item in items)
            if identities(result.raw_candidates) != identities(result.candidates):
                raise ValueError('Augmented observations must preserve the discovered installations.')
        # No effect authority or paths cross a host boundary here. The public
        # strict builder validates the evidence shape on an internal envelope.
        build_executor_inventory_snapshot(result.candidates, server_id='observation',
            executor_id='observation', producer_instance_id=self._token, publication_sequence=1)

    def begin_shutdown(self):
        self._stopped.set()
        self._changed.set()
        for wake in self._wakes.values():
            wake.set()

    async def _join(self):
        # Wait for all workers before exposing ANY unexpected failure. A failed
        # sibling does not prove that a thread/native producer has been joined.
        results = await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if any(isinstance(result, BaseException) for result in results):
            raise RuntimeError('An observation worker ended without a normal join.')

    async def aclose(self):
        self.begin_shutdown()
        if self._join_task is None:
            self._join_task = asyncio.create_task(self._join(), name='inventory-observation-join')
        await asyncio.shield(self._join_task)
