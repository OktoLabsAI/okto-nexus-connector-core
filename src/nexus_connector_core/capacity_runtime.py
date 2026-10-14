"""Installation-level capacity use cases shared by embedded and remote hosts.

A host owns one facade and ledger, and may own many per-session RuntimeCore
objects. Scope authority is supplied by that host's existing authenticated
owner, never by a reservation. This module knows no handoffs, targets or tools.
"""
from __future__ import annotations

import asyncio
import math
from collections.abc import Callable

from .capacity import (CAPACITY_CONTRACT_REVISION, CAPACITY_REASONS,
                       CapacityAssessment, CapacityRequest, CapacityConsumption)
from .clock import RollbackFencedClock, SystemClock
from .models import CoreError, SessionKey
from .ports import CapacitySlotLedger, Clock, RuntimeCapacityAuthority, RuntimeCore


class ExecutionCapacity:
    """Public RuntimeCapacity implementation; no native launch during reserve.

    ``boot_id`` identifies this capacity owner and its monotonic clock, not
    the independent boot of each session's R4 lease reducer. The latter is
    validated by RuntimeCore.capacity_readiness and before every native effect.
    The host enables all productive Core gates before advertising this facade.
    """

    def __init__(self, ledger: CapacitySlotLedger, *, authority: RuntimeCapacityAuthority,
                 runtime_lookup: Callable[[SessionKey], RuntimeCore | None], boot_id: str,
                 clock: Clock | None = None, observation_timeout_seconds: float = 2,
                 max_pending_observations: int = 128, namespace: tuple[str, str] | None = None):
        from .capacity import _text
        _text(boot_id, 'boot_id')
        if namespace is not None:
            if type(namespace) is not tuple or len(namespace) != 2:
                raise ValueError('Invalid capacity owner namespace.')
            for part in namespace:
                _text(part, 'namespace')
        if (not callable(runtime_lookup) or not callable(getattr(authority, 'check_capacity_scope', None))
                or type(observation_timeout_seconds) not in (float, int)
                or not math.isfinite(observation_timeout_seconds) or not 0 < observation_timeout_seconds <= 30
                or type(max_pending_observations) is not int or not 1 <= max_pending_observations <= 4096):
            raise ValueError('Invalid capacity host composition.')
        self._ledger = ledger
        self._authority = authority
        self._lookup = runtime_lookup
        self.boot_id = boot_id
        self._namespace = namespace
        self._clock = clock if isinstance(clock, RollbackFencedClock) else RollbackFencedClock(clock or SystemClock())
        self._timeout = observation_timeout_seconds
        self._pending_limit = max_pending_observations
        self._pending = {}
        self._stale_tasks = set()
        self._closed = False

    async def _bounded_observation(self, key, invoke):
        """A stuck observer never retains the caller or spawns unlimited retries.

        wait_for would await cancellation of an uncooperative callback. Instead
        keep explicit ownership of a bounded, coalesced task until it finishes.
        These are read-only probes; this timeout is never used for native work.
        """
        if self._closed:
            return 'RECOVERING'
        task = self._pending.get(key)
        if task in self._stale_tasks:
            return 'STALE_OBSERVATION'
        if task is None or task.done():
            if task is not None:
                self._pending.pop(key, None)
            if len(self._pending) >= self._pending_limit:
                return 'STALE_OBSERVATION'
            task = asyncio.create_task(invoke())
            self._pending[key] = task
            def finished(done):
                self._stale_tasks.discard(done)
                if self._pending.get(key) is done:
                    self._pending.pop(key, None)
                if not done.cancelled():
                    done.exception()  # Retrieve abandoned failures without leaking their text.
            task.add_done_callback(finished)
        try:
            completed, _ = await asyncio.wait({task}, timeout=self._timeout)
        except asyncio.CancelledError:
            # Other waiters may share this observation; keep its owner alive.
            raise
        if not completed:
            self._stale_tasks.add(task)
            task.cancel()
            return 'STALE_OBSERVATION'
        if task.cancelled():
            return 'STALE_OBSERVATION'
        return task.result()

    async def aclose(self):
        """Bounded observer shutdown. Retained tasks never own productive work."""
        self._closed = True
        tasks = set(self._pending.values())
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self._timeout)
            return len(pending)
        return 0

    def _observation(self):
        now = self._clock.monotonic()
        if not math.isfinite(now):
            raise CoreError('STALE_OBSERVATION', 'capacity_clock')
        return dict(now=now, boot_id=self.boot_id)

    @staticmethod
    def _denial(request, reason):
        return CapacityAssessment(CAPACITY_CONTRACT_REVISION, request.request_hash, reason, 0, 0)

    async def _authority_reason(self, request, action):
        if type(request) is not CapacityRequest:
            raise ValueError('Invalid capacity request.')
        if self._namespace is not None and (request.scope.server_id, request.scope.executor_id) != self._namespace:
            return 'NOT_AUTHORIZED'
        if action not in ('get', 'release') and request.scope.boot_id != self.boot_id:
            return 'STALE_OBSERVATION'
        reason = await self._bounded_observation(('authority', request.request_hash, action),
            lambda: self._authority.check_capacity_scope(request, action=action))
        if reason not in CAPACITY_REASONS:
            raise CoreError('NOT_AUTHORIZED', 'capacity_authority')
        return reason

    async def _require_authority(self, request, action):
        reason = await self._authority_reason(request, action)
        if reason != 'AVAILABLE':
            raise CoreError(reason, 'capacity_authority')

    async def _technical_reason(self, request):
        if request.unit == 'new_session':
            # Approved installation, binding and host readiness are checked by
            # the owner; the physical vacancy is checked atomically by the ledger.
            return 'AVAILABLE'
        s = request.scope
        runtime = self._lookup(SessionKey(s.server_id, s.executor_id, s.session_id))
        if runtime is None:
            return 'RECOVERING'
        readiness = getattr(runtime, 'capacity_readiness', None)
        if not callable(readiness):
            return 'CAPACITY_PROTOCOL_UNSUPPORTED'
        reason = await self._bounded_observation(('readiness', request.request_hash), lambda: readiness(request))
        if reason not in CAPACITY_REASONS:
            return 'RECOVERING'
        return reason

    async def assess_capacity(self, request):
        reason = await self._authority_reason(request, 'assess')
        if reason == 'AVAILABLE':
            reason = await self._technical_reason(request)
        if reason != 'AVAILABLE':
            return self._denial(request, reason)
        result = await self._ledger.assess_capacity_slot(request, **self._observation())
        reason = await self._authority_reason(request, 'assess')
        return result if reason == 'AVAILABLE' else self._denial(request, reason)

    async def try_reserve_capacity(self, request):
        reason = await self._authority_reason(request, 'reserve')
        if reason != 'AVAILABLE':
            return self._denial(request, reason)
        # A retry returns the original durable fact even if work has since
        # started. Neither readiness nor a newer TTL can create another slot.
        prior = await self._ledger.get_capacity_slot(request, **self._observation())
        if prior is not None:
            await self._require_authority(request, 'reserve')
            return prior
        reason = await self._technical_reason(request)
        if reason != 'AVAILABLE':
            return self._denial(request, reason)
        result = await self._ledger.reserve_capacity_slot(request, **self._observation())
        if isinstance(result, CapacityAssessment):
            return result
        reason = await self._authority_reason(request, 'reserve')
        if reason == 'AVAILABLE':
            reason = await self._technical_reason(request)
        if reason != 'AVAILABLE':
            # Persist compensation before reporting a safe refusal. If storage
            # fails, the caller sees an error and looks up the original attempt.
            state = await self._ledger.release_capacity_slot(request, result.reservation_id, **self._observation())
            if state.state not in ('RELEASED', 'EXPIRED_UNCONSUMED'):
                raise CoreError('NEEDS_RECONCILIATION', 'capacity_reserve', possible_effect=True)
            return self._denial(request, reason)
        return result

    async def get_capacity_reservation(self, request):
        await self._require_authority(request, 'get')
        result = await self._ledger.get_capacity_slot(request, **self._observation())
        await self._require_authority(request, 'get')
        return result

    async def consume_capacity(self, request, reservation_id, admitted: CapacityConsumption):
        await self._require_authority(request, 'consume')
        current = await self._ledger.get_capacity_slot(request, **self._observation())
        if current is None or current.reservation_id != reservation_id:
            raise CoreError('RESERVATION_CONFLICT', 'capacity_consume')
        if current.consumption is None and current.state == 'HELD':
            reason = await self._technical_reason(request)
            if reason != 'AVAILABLE':
                raise CoreError(reason, 'capacity_consume')
        result = await self._ledger.consume_capacity_slot(request, reservation_id, admitted, **self._observation())
        reason = await self._authority_reason(request, 'consume')
        if reason != 'AVAILABLE':
            await self._ledger.release_capacity_slot(request, reservation_id, **self._observation())
            raise CoreError(reason, 'capacity_consume')
        return result

    async def release_capacity(self, request, reservation_id, reason):
        if reason not in ('LOST', 'CANCELLED', 'REVOKED', 'ROLLBACK', 'COMPLETED', 'SHUTDOWN'):
            raise ValueError('Invalid capacity release reason.')
        await self._require_authority(request, 'release')
        return await self._ledger.release_capacity_slot(request, reservation_id, **self._observation())

    async def bind_capacity_operation(self, request, reservation_id, binding):
        await self._require_authority(request, 'bind')
        await self._ledger.bind_capacity_operation(request, reservation_id, binding, **self._observation())
        # A reconnect/revocation during storage must stop the caller before send.
        reason = await self._authority_reason(request, 'bind')
        if reason != 'AVAILABLE':
            await self._ledger.release_capacity_slot(request, reservation_id, **self._observation())
            raise CoreError(reason, 'capacity_binding')

    async def bind_admitted_capacity_operation(self, binding):
        """Use the host's existing R4 association before productive dispatch.

        Returns None for ordinary work. A consumed reservation is looked up
        by its canonical operation ID, then its full original scope and both
        hashes are revalidated by the same public binding operation.
        """
        from .receipt_binding_r4 import validate_r4_receipt_binding
        from .models import OperationKey
        value = validate_r4_receipt_binding(binding)
        source = value['source']
        if value['action'] not in ('runtime.open', 'turn.submit'):
            raise ValueError('Capacity binding requires a productive operation.')
        if self._closed or (self._namespace is not None and
                            (source['server_id'], source['executor_id']) != self._namespace):
            raise CoreError('NOT_AUTHORIZED', 'capacity_operation')
        record = await self._ledger.capacity_for_operation(
            OperationKey(source['server_id'], source['executor_id'], source['operation_id']),
            action=value['action'], **self._observation())
        if record is None:
            return None
        await self.bind_capacity_operation(record.request, record.reservation_id, value)
        return record

    async def expire_unconsumed(self, *, limit=128):
        return await self._ledger.expire_capacity_slots(limit=limit, **self._observation())

    async def observe_capacity_revision(self):
        """Trusted owner signal; callers still assess/reserve the exact scope."""
        return await self._ledger.capacity_revision()
