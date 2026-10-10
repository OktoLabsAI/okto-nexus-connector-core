"""R4 grant application inside the Core runtime, after host authentication.

The host persists canonical grants and authenticates the source channel.
These process-local installations never restore a monotonic deadline after
restart; session claims and the existing lease CAS remain durable evidence.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from secrets import token_hex
from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame, R4_PREVIEW_REVISION
from .lease_reducer_r4 import R4LeaseAttempt, R4LeaseProjection, reduce_r4_lease_grant, _validated
from .models import CoreError, ExecutionContext, R4Authority, R4LeaseApplication, SessionKey
from .protocol import canonical_json


@dataclass
class _Installation:
    projection: R4LeaseProjection
    context: ExecutionContext
    pending: asyncio.Task | None = None
    candidate: R4LeaseProjection | None = None
    candidate_context: ExecutionContext | None = None
    revoked: bool = False
    revocation_base: ExecutionContext | None = None
    revocation_revision: int | None = None
    renewal_task: asyncio.Task | None = None


def _context(projection: R4LeaseProjection) -> ExecutionContext:
    scope = projection.scope
    return ExecutionContext(
        server_id=scope["server_id"], executor_id=scope["executor_id"],
        binding_id=scope["binding_id"], agent_id=scope["agent_id"],
        workspace_id=scope["workspace_id"],
        authorization_revision=scope["authorization_revision"],
        configuration_revision=scope["configuration_revision"],
        connection_generation=projection.connection_generation,
        lease_deadline_monotonic=projection.deadline_monotonic,
        allowed_actions=frozenset(projection.allowed_actions),
        session_owner_generation=scope["session_owner_generation"],
        r4_authority=R4Authority(
            scope["session_id"], scope["workspace_binding_id"],
            scope["binding_revision"], scope["credential_epoch"],
            projection.grant_id, projection.lease_id, projection.lease_serial,
            projection.connection_id, projection.boot_id))


def _key(context: ExecutionContext) -> SessionKey:
    if context.r4_authority is None:
        raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_context")
    return SessionKey(context.server_id, context.executor_id,
                      context.r4_authority.session_id)


def _same_open_authority(old: ExecutionContext, new: ExecutionContext) -> bool:
    """Only lease serial/id/deadline may change during an admitted opening."""
    if old.r4_authority is None or new.r4_authority is None:
        return old == new
    return replace(new, lease_deadline_monotonic=old.lease_deadline_monotonic,
                   r4_authority=replace(new.r4_authority,
                       lease_id=old.r4_authority.lease_id,
                       lease_serial=old.r4_authority.lease_serial)) == old


def _application(entry: _Installation, stage: str) -> R4LeaseApplication:
    p = entry.projection
    frame = {
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "lease.applied", "request_id": p.request_id,
        "lease_id": p.lease_id, "lease_serial": p.lease_serial,
        "grant_id": p.grant_id, "scope": dict(p.scope),
        "connection_id": p.connection_id,
        "connection_generation": p.connection_generation,
        "application_stage": stage,
    }
    return R4LeaseApplication(entry.context,
                              decode_r4_frame(canonical_json(frame)))


class R4LeaseRuntime:
    """Internal runtime mixin; hosts use the public RuntimeCore methods."""

    def _init_r4_leases(self) -> None:
        self._r4_boot_id = token_hex(24)
        self._r4_leases: dict[SessionKey, _Installation] = {}
        self._r4_requests: dict[SessionKey, R4LeaseAttempt] = {}
        self._r4_lease_tasks: set[asyncio.Task] = set()

    @property
    def r4_boot_id(self) -> str:
        """A local runtime incarnation, never a reusable restart authority."""
        return self._r4_boot_id

    async def begin_r4_lease_request(self, *, scope: Mapping[str, Any], grant_id: str,
                                      connection_id: str, connection_generation: int,
                                      purpose: str) -> R4LeaseAttempt:
        """Capture a local nonce and t0 before transport sends a lease request.

        Starting a newer request supersedes an unanswered request. A response
        to the old nonce can no longer install or extend any authority.
        """
        from .lease_reducer_r4 import r4_lease_renew_frame
        async with self._lock:
            if self._shutting_down:
                raise CoreError("RUNTIME_DRAINING", "r4_request")
            if not isinstance(scope, Mapping):
                raise CoreError("VALIDATION_ERROR", "r4_request")
            scope = deepcopy(dict(scope))
            # Schema validation comes before indexing supplied scope keys.
            probe = R4LeaseAttempt(token_hex(24), grant_id, 0, scope,
                                   connection_id, connection_generation, purpose,
                                   self._r4_boot_id, self._clock.monotonic())
            r4_lease_renew_frame(probe)
            key = SessionKey(scope["server_id"], scope["executor_id"], scope["session_id"])
            entry = self._r4_leases.get(key)
            if entry is not None and entry.pending is not None:
                raise CoreError("LEASE_UPDATE_PENDING", "r4_request", retry_safe=True)
            if entry is not None and entry.revoked:
                raise CoreError("AGENT_REVOKED", "r4_request")
            if ((entry is None and purpose != "initial") or
                    (entry is not None and purpose == "initial")):
                raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_request")
            # Retire authority only when it has no live opening/session. Its
            # nonce disappears too; an old grant can never reanchor a deadline.
            for old_key, old in tuple(self._r4_leases.items()):
                binding = self._sessions.get(old_key)
                if (old_key != key and old.pending is None and
                        old_key not in self._opening and old_key not in self._uncertain_opens and
                        (binding is None or binding.closed) and
                        (old.revoked or probe.sent_at_monotonic >= old.context.lease_deadline_monotonic or
                         (binding is not None and binding.closed) or
                         self._session_tombstones.get(old_key) is not None)):
                    self._r4_leases.pop(old_key)
                    self._r4_requests.pop(old_key, None)
            for old_key, old in tuple(self._r4_requests.items()):
                if (old_key not in self._r4_leases and
                        probe.sent_at_monotonic >= old.sent_at_monotonic + self._max_lease_seconds):
                    self._r4_requests.pop(old_key)
            if key not in self._r4_requests and len(self._r4_requests) >= self._max_owned_sessions + self._max_concurrent_opens:
                raise CoreError("CAPACITY_EXCEEDED", "r4_request", retry_safe=True)
            request = replace(probe, expected_lease_serial=(entry.projection.lease_serial if entry else 0))
            self._r4_requests[key] = request
            return replace(request, scope=deepcopy(scope))

    def _own_r4_task(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._r4_lease_tasks.add(task)

        def completed(done):
            self._r4_lease_tasks.discard(done)
            if not done.cancelled():
                done.exception()  # A canceled waiter does not discard the producer.

        task.add_done_callback(completed)
        return task

    def _check_r4_context(self, context: ExecutionContext, action: str,
                          session_id: str | None = None, *,
                          containment_reply: bool = False) -> None:
        authority = context.r4_authority
        if authority is None:
            if session_id is not None and SessionKey(
                    context.server_id, context.executor_id, session_id) in self._r4_leases:
                raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_context", retry_safe=True)
            return
        key = _key(context)
        entry = self._r4_leases.get(key)
        if (entry is None or authority.boot_id != self._r4_boot_id or
                (session_id is not None and session_id != key.session_id)):
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_context", retry_safe=True)
        if entry.revoked:
            raise CoreError("AGENT_REVOKED", "r4_context", retry_safe=True)
        containment = action in {"turn.interrupt", "runtime.close"} or containment_reply
        if entry.pending is not None:
            candidate = entry.candidate
            # A serial/deadline renewal does not revoke existing containment.
            # A different owner, source, scope or grant must never borrow the
            # previous context while its durable installation is uncertain.
            compatible = (candidate is not None and
                candidate.scope == entry.projection.scope and
                candidate.connection_id == entry.projection.connection_id and
                candidate.connection_generation == entry.projection.connection_generation and
                candidate.grant_id == entry.projection.grant_id and
                action in candidate.allowed_actions)
            if not containment or not compatible:
                raise CoreError("LEASE_UPDATE_PENDING", "r4_context", retry_safe=True)
        binding = self._sessions.get(key)
        if binding is not None and binding.superseded:
            raise CoreError("STALE_GENERATION", "r4_context", retry_safe=True)
        if context != entry.context:
            raise CoreError("STALE_GENERATION", "r4_context", retry_safe=True)
        if not containment and self._clock.monotonic() >= context.lease_deadline_monotonic:
            raise CoreError("LEASE_EXPIRED", "r4_context", retry_safe=True)
        if action not in context.allowed_actions:
            raise CoreError("BINDING_NOT_AUTHORIZED", "r4_context", retry_safe=True)

    def _r4_open_blocked(self, context: ExecutionContext, session_id: str) -> bool:
        try:
            self._current_open_context(context, session_id)
            return False
        except CoreError:
            return True

    def _current_open_context(self, admitted: ExecutionContext,
                              session_id: str | None = None) -> ExecutionContext:
        # Internal continuation only. Public entry points still require the
        # exact installed context; productive turns never borrow old authority.
        current = admitted
        if admitted.r4_authority is not None:
            entry = self._r4_leases.get(_key(admitted))
            if entry is None or not _same_open_authority(admitted, entry.context):
                raise CoreError("STALE_GENERATION", "open", retry_safe=True)
            current = entry.context
        self._check_r4_context(current, "runtime.open", session_id)
        return current

    def _r4_revoked(self, session: SessionKey) -> bool:
        entry = self._r4_leases.get(session)
        return entry is not None and entry.revoked

    def _r4_pending(self, session: SessionKey) -> bool:
        entry = self._r4_leases.get(session)
        return entry is not None and entry.pending is not None

    async def install_r4_lease(self, attempt: R4LeaseAttempt,
                               grant: Mapping[str, Any]) -> R4LeaseApplication:
        """Apply one host-authenticated grant, then return its application ACK.

        The original attempt captures t0 before sending. The host checks the
        source connection before calling this method. Replay never extends t0.
        Cancellation detaches the waiter from an already delivered renewal.
        """
        if not isinstance(attempt, R4LeaseAttempt) or attempt.boot_id != self._r4_boot_id:
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_install")
        # Copy mutable caller data before an await or retaining an attempt.
        if not isinstance(attempt.scope, Mapping):
            raise CoreError("VALIDATION_ERROR", "r4_install")
        attempt = replace(attempt, scope=deepcopy(dict(attempt.scope)))
        grant = _validated(grant, "lease.granted")
        scope = attempt.scope
        # Reducer validation precedes indexing untrusted scope keys.
        from .lease_reducer_r4 import r4_lease_renew_frame
        r4_lease_renew_frame(attempt)
        key = SessionKey(scope["server_id"], scope["executor_id"], scope["session_id"])
        async with self._lock:
            if self._shutting_down:
                raise CoreError("RUNTIME_DRAINING", "r4_install")
            if self._r4_requests.get(key) != attempt:
                raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_install")
            entry = self._r4_leases.get(key)
            if entry is not None and entry.revoked:
                raise CoreError("AGENT_REVOKED", "r4_install")
            previous = entry.projection if entry is not None else None
            # A delivered renewal already passed the old lease's deadline
            # check. Correlate retries with that candidate, without repeating
            # admission or reanchoring t0 after a late durable commit.
            pending_candidate = entry.candidate if entry is not None and entry.pending is not None else None
            candidate = reduce_r4_lease_grant(
                pending_candidate or previous, attempt, grant,
                received_at_monotonic=self._clock.monotonic())
            if self._clock.monotonic() >= candidate.deadline_monotonic:
                raise CoreError("LEASE_EXPIRED", "r4_install")
            if entry is not None and entry.pending is not None:
                if candidate != entry.candidate:
                    raise CoreError("LEASE_CONFLICT", "r4_install")
                task = entry.pending
                if task.done():
                    binding = self._sessions.get(key)
                    if (binding is not None and binding.context == entry.candidate_context and
                            not binding.closed and not binding.closing and not binding.draining and
                            not binding.revoked and not binding.lease_hold):
                        entry.context = entry.candidate_context
                        entry.projection = candidate
                        entry.pending = None
                        return _application(entry, "RENEWED")
                    if binding is not None and (binding.lease_hold or binding.lease_cas_pending):
                        raise CoreError("LEASE_UPDATE_PENDING", "r4_install", retry_safe=True)
                    if self._clock.monotonic() >= entry.context.lease_deadline_monotonic:
                        raise CoreError("LEASE_EXPIRED", "r4_install")
                    entry.pending = None  # Proven failed producer; same correlated grant may retry.
                else:
                    # Wait outside the global lock on the original producer.
                    pass
            if entry is not None and entry.pending is not None:
                task = entry.pending
            elif candidate is previous:
                if self._clock.monotonic() >= candidate.deadline_monotonic:
                    raise CoreError("LEASE_EXPIRED", "r4_install")
                return _application(entry, "INSTALLED" if candidate.lease_serial == 1 else "RENEWED")
            else:
                context = _context(candidate)
                if entry is None:
                    if key in self._sessions or key in self._opening or key in self._uncertain_opens:
                        raise CoreError("SESSION_CONFLICT", "r4_install")
                    if len(self._r4_leases) >= self._max_owned_sessions + self._max_concurrent_opens:
                        raise CoreError("CAPACITY_EXCEEDED", "r4_install", retry_safe=True)
                    entry = _Installation(candidate, context)
                    self._r4_leases[key] = entry
                    return _application(entry, "INSTALLED")
                if (not context.allowed_actions.issubset(entry.context.allowed_actions) and
                        context.authorization_revision == entry.context.authorization_revision):
                    raise CoreError("BINDING_NOT_AUTHORIZED", "r4_install")
                if (key in self._uncertain_opens or
                        (key in self._opening and not _same_open_authority(entry.context, context))):
                    raise CoreError("RECONNECT_BUSY", "r4_install", retry_safe=True)
                if key not in self._sessions:
                    # Before open, installation is process-local and has no native effect.
                    entry.context, entry.projection = context, candidate
                    return _application(entry, "RENEWED")
                entry.candidate, entry.candidate_context = candidate, context
                task = self._own_r4_task(self._install_r4_renewal(key, entry, context, candidate))
                entry.renewal_task = task
                entry.pending = task
        return await asyncio.shield(task)

    async def _install_r4_renewal(self, key, entry, context, candidate):
        await self.renew_lease(key, context,
                              expected_connection_generation=entry.context.connection_generation)
        binding = self._sessions.get(key)
        if (self._shutting_down or entry.revoked or binding is None or binding.closed or
                binding.closing or binding.draining or
                binding.revoked or binding.lease_hold or binding.context != context or
                self._clock.monotonic() >= context.lease_deadline_monotonic):
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_install")
        entry.context, entry.projection = context, candidate
        entry.pending = None
        return _application(entry, "RENEWED")

    def r4_operation_context(self, frame: Mapping[str, Any], *,
                              connection_id: str,
                              connection_generation: int) -> ExecutionContext:
        """Match a validated operation to the installed grant and source channel."""
        operation = _validated(frame, "operation.submit")
        key = SessionKey(operation["server_id"], operation["executor_id"], operation["session_id"])
        entry = self._r4_leases.get(key)
        if entry is None:
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_context")
        p = entry.projection
        if (operation["connection_id"] != connection_id or
                operation["connection_generation"] != connection_generation or
                connection_id != p.connection_id or connection_generation != p.connection_generation or
                operation["grant_id"] != p.grant_id or
                any(operation[key] != value for key, value in p.scope.items())):
            raise CoreError("STALE_GENERATION", "r4_context")
        containment_reply = False
        if operation['action'] in {'approval.decide', 'input.provide'}:
            payload = operation['payload']
            if (payload['decision'] in {'decline', 'cancel'} and
                    payload.get('response') is None and payload.get('response_ref') is None and
                    payload.get('response_digest') is None):
                # Derive the exemption from the validated native decision;
                # no host- or wire-supplied containment flag grants authority.
                from .decision_bridge_r4 import r4_native_decision_operation
                r4_native_decision_operation(operation)
                containment_reply = True
        self._check_r4_context(entry.context, operation["action"], key.session_id,
                               containment_reply=containment_reply)
        return entry.context

    def r4_native_action_context(self, scope: Mapping[str, Any], *,
                                 connection_id: str, connection_generation: int) -> ExecutionContext:
        """Read current installed session authority for a separate domain capability.

        Runtime allowed_actions remains the seven-operation wire vocabulary.
        The native bridge checks its separate canonical capability ceiling.
        This accessor grants no runtime operation and never extends a deadline.
        """
        from .native_action_bridge import native_action_scope
        scope = native_action_scope(scope)
        key = SessionKey(scope['server_id'], scope['executor_id'], scope['session_id'])
        entry = self._r4_leases.get(key)
        if self._shutting_down:
            raise CoreError('RUNTIME_DRAINING', 'native_action_context')
        if entry is None:
            raise CoreError('LEASE_REVALIDATION_REQUIRED', 'native_action_context')
        p = entry.projection
        if (type(connection_generation) is not int or connection_generation != p.connection_generation
                or connection_id != p.connection_id or canonical_json(scope) != canonical_json(dict(p.scope))
                or entry.context.r4_authority.boot_id != self._r4_boot_id):
            raise CoreError('STALE_GENERATION', 'native_action_context')
        if entry.revoked:
            raise CoreError('AGENT_REVOKED', 'native_action_context')
        if entry.pending is not None:
            raise CoreError('LEASE_UPDATE_PENDING', 'native_action_context')
        binding = self._sessions.get(key)
        if binding is None and key not in self._opening:
            raise CoreError('SESSION_UNKNOWN', 'native_action_context')
        if binding is not None and any((binding.closed, binding.closing, binding.draining,
                                       binding.revoked, binding.superseded)):
            raise CoreError('SESSION_UNKNOWN', 'native_action_context')
        if self._clock.monotonic() >= entry.context.lease_deadline_monotonic:
            raise CoreError('LEASE_EXPIRED', 'native_action_context')
        return entry.context

    async def revoke_r4_lease(self, context: ExecutionContext, *,
                              authorization_revision: int) -> R4LeaseApplication:
        """Fence immediately, then acknowledge the actual Core revocation.

        A pending opening retains its guard and owner. An uncertain or busy
        native opening yields no application ACK until it can be reconciled.
        """
        key = _key(context)
        if type(authorization_revision) is not int or not 0 <= authorization_revision <= 9007199254740991:
            raise CoreError("VALIDATION_ERROR", "r4_revoke")
        async with self._lock:
            entry = self._r4_leases.get(key)
            if entry is None:
                raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_revoke")
            if entry.revoked:
                if context != entry.revocation_base or authorization_revision != entry.revocation_revision:
                    raise CoreError("STALE_GENERATION", "r4_revoke")
                if entry.pending is None:
                    return _application(entry, "REVOKED")
                if not entry.pending.done():
                    task = entry.pending
                else:
                    task = self._own_r4_task(self._revoke_r4_installed(key, entry))
                    entry.pending = task
            else:
                newest_revision = max(context.authorization_revision,
                                      entry.candidate_context.authorization_revision
                                      if entry.pending is not None and entry.candidate_context else 0)
                if context != entry.context or authorization_revision <= newest_revision:
                    raise CoreError("STALE_GENERATION", "r4_revoke")
                entry.revoked = True
                entry.revocation_base, entry.revocation_revision = context, authorization_revision
                task = self._own_r4_task(self._revoke_r4_installed(key, entry))
                entry.pending = task
        return await asyncio.shield(task)

    async def _revoke_r4_installed(self, key, entry):
        # A delivered CAS may still commit. Fence immediately above, retain
        # its producer, and revoke the generation actually installed below.
        renewal = entry.renewal_task
        if renewal is not None and not renewal.done():
            done, _ = await asyncio.wait({renewal}, timeout=self._reconnect_fence_seconds)
            if not done:
                raise CoreError("REVOKE_BUSY", "r4_revoke", retry_safe=True)
        opening = self._opening.get(key)
        if opening is not None:
            try:
                await asyncio.wait_for(opening.finished.wait(), self._reconnect_fence_seconds)
            except TimeoutError as exc:
                raise CoreError("REVOKE_BUSY", "r4_revoke", retry_safe=True) from exc
        if key in self._uncertain_opens:
            raise CoreError("REVOKE_BUSY", "r4_revoke", retry_safe=True)
        binding = self._sessions.get(key)
        base = binding.context if binding is not None else entry.context
        if binding is not None and (binding.lease_hold or binding.lease_cas_pending):
            raise CoreError("REVOKE_BUSY", "r4_revoke", retry_safe=True)
        if entry.candidate_context is not None and base.r4_authority == entry.candidate_context.r4_authority:
            entry.projection = entry.candidate
        context = replace(base, authorization_revision=entry.revocation_revision)
        if binding is not None:
            if binding.revoked:
                # A lost CAS acknowledgement may already have fenced the
                # binding without copying the proposed revision into memory.
                # Recover the acknowledgement only from the complete durable
                # row; a revoked row from another generation is not our ACK.
                lease = await self._journal.get_session_lease(key)
                if (lease is None or not lease.revoked or
                        lease.connection_generation != base.connection_generation or
                        lease.owner_generation != base.session_owner_generation or
                        lease.authorization_revision != entry.revocation_revision or
                        lease.configuration_revision != base.configuration_revision):
                    raise CoreError("STALE_GENERATION", "r4_revoke")
            else:
                await self.revoke_lease(key, context,
                                       expected_connection_generation=base.connection_generation)
        entry.context = replace(context, allowed_actions=frozenset(),
                                lease_deadline_monotonic=self._clock.monotonic())
        entry.pending = None
        return _application(entry, "REVOKED")
