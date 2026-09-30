"""Domain capability authority is separate from the seven R4 runtime verbs."""
import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, CloseOperation, ShutdownPolicy
from nexus_connector_core.native_action_bridge import (
    ContextGet, HandoffClaim, HandoffComplete, NativeActionGrant,
    ScopedNativeActionBridge, native_action_request_body,
)
from test_native_action_bridge import Backend
from test_r4_runtime_leases import attempt, grant, open_session
from test_runtime import FakeClock, make_runtime


def native_grant(req, clock, **changes):
    scope = dict(req.scope)
    return replace(NativeActionGrant(
        "native-cap:session", scope["server_id"], scope["executor_id"],
        scope["binding_id"], scope["agent_id"], scope["workspace_id"],
        scope["session_id"], req.connection_generation,
        scope["authorization_revision"], scope["configuration_revision"],
        clock.now + 50, frozenset({"handoff.get", "handoff.claim", "handoff.complete"}),
        scope, req.connection_id), **changes)


def test_runtime_only_lease_allows_scoped_domain_capability_and_freezes_scope(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, _ = make_runtime(tmp_path, clock=clock)
        try:
            req = await attempt(runtime, clock)
            context = (await runtime.install_r4_lease(req, grant(req))).context
            await open_session(runtime, context)
            backend = Backend()
            cap = native_grant(req, clock)
            bridge = ScopedNativeActionBridge(backend, cap, clock=clock, r4_runtime=runtime)
            cap.r4_scope["workspace_binding_id"] = "mutated-after-construction"
            assert not (context.allowed_actions & cap.allowed_actions)
            base = ("domain-action", "session", cap.capability_ref, "work")
            for request in (ContextGet(*base), HandoffClaim(*base, "key"),
                            HandoffComplete(*base, 1, {"summary": "Done."})):
                await bridge.invoke(request, context)
            assert [row[0] for row in backend.calls] == ["get", "claim", "complete"]
            assert runtime.r4_native_action_context(req.scope, connection_id="connection",
                                                    connection_generation=1) == context
            for changed in (
                replace(context, r4_authority=None),
                replace(context, r4_authority=replace(context.r4_authority, credential_epoch=True)),
                replace(context, lease_deadline_monotonic=context.lease_deadline_monotonic + 1),
                replace(context, allowed_actions=context.allowed_actions | {"handoff.claim"}),
            ):
                with pytest.raises(CoreError):
                    await bridge.invoke(HandoffClaim(*base, "key"), changed)
            assert len(backend.calls) == 3
            legacy = ScopedNativeActionBridge(backend, replace(cap, r4_scope=None,
                                               r4_connection_id=None), clock=clock)
            with pytest.raises(CoreError):
                await legacy.invoke(ContextGet(*base), context)
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


@pytest.mark.parametrize("fence", ["unopened", "revoked", "expired", "closed", "wrong_connection", "wrong_scope"])
def test_current_runtime_authority_fences_domain_before_backend(tmp_path, fence):
    async def run():
        clock = FakeClock()
        runtime, journal, _ = make_runtime(tmp_path, clock=clock)
        backend = Backend()
        try:
            req = await attempt(runtime, clock)
            context = (await runtime.install_r4_lease(req, grant(req))).context
            cap = native_grant(req, clock)
            if fence != "unopened":
                await open_session(runtime, context)
            if fence == "revoked":
                await runtime.revoke_r4_lease(context, authorization_revision=2)
            elif fence == "expired":
                clock.advance(61)
            elif fence == "closed":
                await runtime.close(CloseOperation("close", "session", "Done.", ShutdownPolicy(1, 1)), context)
            elif fence == "wrong_connection":
                cap = replace(cap, r4_connection_id="old")
            elif fence == "wrong_scope":
                cap = replace(cap, r4_scope={**req.scope, "credential_epoch": 2})
            bridge = ScopedNativeActionBridge(backend, cap, clock=clock, r4_runtime=runtime)
            with pytest.raises(CoreError):
                await bridge.invoke(HandoffClaim("claim", "session", cap.capability_ref, "work", "key"), context)
            assert not backend.calls
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


@pytest.mark.parametrize("mutating", [False, True])
def test_revocation_while_backend_is_running_discards_response(tmp_path, mutating):
    async def run():
        clock = FakeClock()
        runtime, journal, _ = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        class HeldBackend:
            async def get_context(self, request, context):
                calls.append(request.operation_id)
                entered.set()
                await release.wait()
                return {"handoff_id": request.handoff_id, "status": "CLAIMED"}
            claim_handoff = get_context
        try:
            req = await attempt(runtime, clock)
            context = (await runtime.install_r4_lease(req, grant(req))).context
            await open_session(runtime, context)
            cap = native_grant(req, clock)
            bridge = ScopedNativeActionBridge(HeldBackend(), cap, clock=clock, r4_runtime=runtime)
            base = ("original-id", "session", cap.capability_ref, "work")
            request = HandoffClaim(*base, "key") if mutating else ContextGet(*base)
            task = asyncio.create_task(bridge.invoke(request, context))
            await asyncio.wait_for(entered.wait(), 2)
            await runtime.revoke_r4_lease(context, authorization_revision=2)
            release.set()
            with pytest.raises(CoreError) as error:
                await task
            assert error.value.code == ("OUTCOME_UNKNOWN" if mutating else "AGENT_REVOKED")
            assert error.value.possible_effect is mutating
            assert not error.value.retry_safe
            if mutating:
                assert error.value.operation_id == "original-id"
            assert calls == ["original-id"]
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_pending_renewal_fences_native_domain_and_old_context(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, _ = make_runtime(tmp_path, clock=clock)
        entered, release = asyncio.Event(), asyncio.Event()
        original = journal.cas_session_lease
        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        try:
            req = await attempt(runtime, clock)
            context = (await runtime.install_r4_lease(req, grant(req))).context
            await open_session(runtime, context)
            backend = Backend()
            cap = native_grant(req, clock)
            bridge = ScopedNativeActionBridge(backend, cap, clock=clock, r4_runtime=runtime)
            request = ContextGet("read", "session", cap.capability_ref, "work")
            journal.cas_session_lease = held
            clock.advance(1)
            renewal = await attempt(runtime, clock, purpose="renew")
            task = asyncio.create_task(runtime.install_r4_lease(renewal, grant(renewal)))
            await asyncio.wait_for(entered.wait(), 2)
            with pytest.raises(CoreError, match="LEASE_UPDATE_PENDING"):
                await bridge.invoke(request, context)
            release.set()
            current = (await task).context
            with pytest.raises(CoreError, match="STALE_GENERATION"):
                await bridge.invoke(request, context)
            await bridge.invoke(request, current)
            assert len(backend.calls) == 1
        finally:
            release.set()
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(run())


def test_wire_body_preserves_identity_and_detaches_nested_result():
    scope = dict(server_id="srv", executor_id="exe", binding_id="binding", agent_id="agent",
                 workspace_id="ws", workspace_binding_id="wxb", session_id="session",
                 session_owner_generation=1, authorization_revision=1, configuration_revision=1,
                 binding_revision=1, credential_epoch=1)
    result = {"summary": ["Done."]}
    body = native_action_request_body(HandoffComplete("original-id", "session",
        "native-cap:session", "work", 2, result), scope)
    result["summary"].append("Changed.")
    assert body["action_id"] == "original-id"
    assert body["payload"] == {"handoff_id": "work", "claim_epoch": 2,
                               "result": {"summary": ["Done."]}}
    with pytest.raises(CoreError):
        native_action_request_body(ContextGet("read", "session", "native-cap:session", "work"),
                                   dict(scope, credential_epoch=True))
