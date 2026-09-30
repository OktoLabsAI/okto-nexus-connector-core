"""Owned, coalesced close operations with one drain/interrupt deadline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .models import CoreError, SessionKey
from .protocol import intent_hash


@dataclass(slots=True)
class _CloseAttempt:
    operation_id: str
    digest: str
    deadline: float
    task: asyncio.Task | None = None


class CloseRuntimeMixin:
    async def _close_policy(self, semantic, context, policy, *, wait_for_completion=False):
        session = SessionKey(context.server_id, context.executor_id, semantic.session_id)
        digest = intent_hash(semantic, context)
        # Same-operation waiters share the producer, including while the
        # journal or native write is stalled. No second close is scheduled.
        attempt = self._policy_closes.get(session)
        if attempt is None:
            old = await self._existing(semantic, context)
            if old is not None:
                return old
            async with self._lock:
                attempt = self._policy_closes.get(session)
                if attempt is None:
                    binding = self._session(semantic.session_id, context)
                    if binding.closed or binding.closing or binding.draining or self._shutting_down:
                        raise CoreError("SESSION_CLOSING", "close", retry_safe=True)
                    attempt = _CloseAttempt(semantic.operation_id, digest,
                        asyncio.get_running_loop().time() + policy.drain_seconds + policy.interrupt_seconds)
                    self._policy_closes[session] = attempt
                    attempt.task = asyncio.create_task(self._run_policy_close(
                        session, binding, semantic, context, policy, attempt))
                    def completed(task):
                        # Retrieve errors even when every public waiter left.
                        if not task.cancelled():
                            task.exception()
                        if self._policy_closes.get(session) is attempt:
                            del self._policy_closes[session]
                    attempt.task.add_done_callback(completed)
        if attempt.operation_id != semantic.operation_id:
            raise CoreError("SESSION_CLOSING", "close", retry_safe=True)
        if attempt.digest != digest:
            raise CoreError("OPERATION_CONFLICT", "close", operation_id=semantic.operation_id)
        if wait_for_completion:
            # Trusted operation owners may join the retained producer instead
            # of observing only until its physical drain/interrupt deadline.
            # Cancellation still detaches only this waiter.
            return await asyncio.shield(attempt.task)
        # Observation timeout is not cancellation of an owned native unit.
        # The eventual receipt is committed by the same producer, queryable
        # under the same ID. A timeout never fabricates a durable receipt.
        await asyncio.wait((attempt.task,), timeout=max(
            0, attempt.deadline - asyncio.get_running_loop().time()))
        if attempt.task.done():
            return attempt.task.result()
        raise CoreError("OUTCOME_UNKNOWN", "close", possible_effect=True,
                        operation_id=semantic.operation_id)

    async def _run_policy_close(self, session, binding, semantic, context, policy, attempt):
        async def effect():
            self._authorize(context, "runtime.close")
            self._session(semantic.session_id, context)
            async with self._lock:
                binding.draining = True
                # A managed owned resource has a force deadline independent
                # of journal/normal/control locks. Attach never gets force.
                self._schedule_force(session, binding, attempt.deadline)
                if binding.shutdown_task is None or binding.shutdown_task.done():
                    binding.shutdown_task = asyncio.create_task(self._shutdown_session(
                        session, binding, policy, deadline=attempt.deadline))
                physical = binding.shutdown_task
            outcome = await asyncio.shield(physical)
            if outcome not in {"graceful", "forced", "already_closed"} or not binding.closed:
                raise CoreError("OUTCOME_UNKNOWN", "close", possible_effect=True,
                                operation_id=semantic.operation_id)
        # R4 close is complete only after physical stop and owned-slot release.
        # Commit the terminal fact in the retained producer before publishing.
        return await self._kernel.execute(semantic, context, effect,
            completion_stage="SUCCEEDED" if context.r4_authority is not None else "SUBMITTED")
