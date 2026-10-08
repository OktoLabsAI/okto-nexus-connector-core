"""Minimal effect-admission kernel; host performs authorization first."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .clock import RollbackFencedClock, SystemClock
from .journal import SQLiteJournal
from .models import CoreError, EffectNotSent, EffectRejected, ExecutionContext, Operation, OperationKey, OperationReceipt, OperationNotAdmitted
from .ports import Journal, Clock
from .protocol import intent_hash


class OperationKernel:
    def __init__(self, journal: "Journal", clock: Clock | None = None):
        self.journal = journal
        self.clock = (clock if isinstance(clock, RollbackFencedClock)
                      else RollbackFencedClock(clock or SystemClock()))

    async def execute(self, operation: Operation, context: ExecutionContext,
                      effect: Callable[[], Awaitable[str | None]], *,
                      containment: bool | None = None,
                      completion_stage: str = "SUBMITTED") -> OperationReceipt:
        # Only a caller that has observed completion may request a terminal
        # receipt. Validate before admission or any native effect.
        if type(completion_stage) is not str or completion_stage not in {"SUBMITTED", "SUCCEEDED"}:
            raise CoreError("VALIDATION_ERROR", "admission", retry_safe=True)
        # C7/W04: callers with a derived per-operation classification
        # (a strictly negative approval reply) pass it explicitly; the
        # default stays action-based.
        if containment is None:
            containment = operation.action in {"turn.interrupt",
                                               "runtime.close"}

        def _expired() -> bool:
            # Lease revalidation (PC03): an effect must never start under
            # authorization that expired while the operation waited on
            # durable I/O or thread scheduling. Containment controls stay
            # allowed past the deadline by contract (RC-03-06).
            return (not containment and
                    self.clock.monotonic() >= context.lease_deadline_monotonic)

        if _expired():
            raise CoreError("AGENT_REVOKED", "admission", retry_safe=True,
                            operation_id=operation.operation_id)
        if operation.action not in context.allowed_actions:
            raise CoreError("BINDING_NOT_AUTHORIZED", "admission", retry_safe=True,
                            operation_id=operation.operation_id)
        digest = intent_hash(operation, context)
        key = OperationKey(context.server_id, context.executor_id,
                           operation.operation_id)
        admission = dict(critical=operation.action in {
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
        try:
            receipt, fresh = await self.journal.admit(
                key, digest, operation.session_id, **admission)
        except CoreError as error:
            # Productive refusals must not consume the capacity reserved for
            # interrupt/close. Give the host a correlated no-effect fact to
            # persist in its already-reserved publication obligation instead.
            if (operation.action not in {'turn.submit', 'turn.steer'} or
                    error.code != 'JOURNAL_FULL' or error.stage != 'admission' or error.possible_effect or
                    not error.retry_safe):
                raise
            raise OperationNotAdmitted(OperationReceipt(
                operation.operation_id, digest, 'FAILED', False, True,
                operation.session_id, error_code=error.code)) from error
        if not fresh:
            return receipt
        if _expired():
            # The admission await itself may have crossed the deadline
            # (RC-03-01). No effect has started and no possible-effect
            # marker exists yet: the durable row already reflects a safe,
            # unmarked admission - refuse without inventing a transition.
            raise CoreError("AGENT_REVOKED", "native_send", retry_safe=True,
                            operation_id=operation.operation_id)
        await self.journal.mark_possible_effect(key)
        if _expired():
            # The marker await crossed the deadline (RC-03-02, audit F02).
            # Still proven no-write: the effect callable never ran.
            await self.journal.record_not_sent(key, "AGENT_REVOKED")
            raise CoreError("AGENT_REVOKED", "native_send", retry_safe=True,
                            operation_id=operation.operation_id)
        try:
            native_id = await effect()
        except EffectNotSent as exc:
            await self.journal.record_not_sent(key, exc.code)
            raise CoreError(exc.code, "native_send",
                            retry_safe=True,
                            operation_id=operation.operation_id) from exc
        except EffectRejected as exc:
            rejected = OperationReceipt(operation.operation_id, digest,
                "FAILED", True, False, operation.session_id,
                error_code=exc.failure_code)
            return await self.journal.record_receipt(key, rejected)
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
        submitted = OperationReceipt(operation.operation_id, digest, completion_stage,
                                     True, False, operation.session_id, native_id)
        return await self.journal.record_receipt(key, submitted)
