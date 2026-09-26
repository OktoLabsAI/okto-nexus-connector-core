"""Minimal effect-admission kernel; host performs authorization first."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .clock import RollbackFencedClock, SystemClock
from .journal import SQLiteJournal
from .models import CoreError, EffectNotSent, ExecutionContext, Operation, OperationKey, OperationReceipt
from .ports import Clock
from .protocol import intent_hash


class OperationKernel:
    def __init__(self, journal: SQLiteJournal, clock: Clock | None = None):
        self.journal = journal
        self.clock = (clock if isinstance(clock, RollbackFencedClock)
                      else RollbackFencedClock(clock or SystemClock()))

    async def execute(self, operation: Operation, context: ExecutionContext,
                      effect: Callable[[], Awaitable[str | None]]) -> OperationReceipt:
        if (self.clock.monotonic() >= context.lease_deadline_monotonic and
                operation.action not in {"turn.interrupt", "runtime.close"}):
            raise CoreError("AGENT_REVOKED", "admission", retry_safe=True,
                            operation_id=operation.operation_id)
        if operation.action not in context.allowed_actions:
            raise CoreError("BINDING_NOT_AUTHORIZED", "admission", retry_safe=True,
                            operation_id=operation.operation_id)
        digest = intent_hash(operation, context)
        key = OperationKey(context.server_id, context.executor_id,
                           operation.operation_id)
        receipt, fresh = await self.journal.admit(key, digest,
                                                 operation.session_id,
                                                 critical=operation.action in {
                                                     "turn.interrupt", "runtime.close",
                                                     "approval.decide", "input.provide"},
                                                 claim_session=operation.action == "runtime.open",
                                                 connection_generation=(
                                                     context.connection_generation
                                                     if operation.action == "runtime.open" else None),
                                                 session_owner_generation=(
                                                     context.session_owner_generation
                                                     if operation.action == "runtime.open" else None),
                                                 authorization_revision=(
                                                     context.authorization_revision
                                                     if operation.action == "runtime.open" else None),
                                                 configuration_revision=(
                                                     context.configuration_revision
                                                     if operation.action == "runtime.open" else None))
        if not fresh:
            return receipt
        await self.journal.mark_possible_effect(key)
        try:
            native_id = await effect()
        except EffectNotSent as exc:
            await self.journal.record_not_sent(key, exc.code)
            raise CoreError(exc.code, "native_send",
                            retry_safe=True,
                            operation_id=operation.operation_id) from exc
        except CoreError as exc:
            if exc.retry_safe and not exc.possible_effect:
                await self.journal.record_not_sent(key, exc.code)
                raise
            unknown = OperationReceipt(operation.operation_id, digest,
                                       "OUTCOME_UNKNOWN", True, False,
                                       operation.session_id,
                                       error_code="OUTCOME_UNKNOWN")
            await self.journal.record_receipt(key, unknown)
            raise
        except BaseException:
            # A write or spawn may have happened before the exception/cancellation.
            unknown = OperationReceipt(operation.operation_id, digest,
                                       "OUTCOME_UNKNOWN", True, False,
                                       operation.session_id,
                                       error_code="OUTCOME_UNKNOWN")
            await self.journal.record_receipt(key, unknown)
            raise
        submitted = OperationReceipt(operation.operation_id, digest, "SUBMITTED",
                                     True, False, operation.session_id, native_id)
        return await self.journal.record_receipt(key, submitted)
