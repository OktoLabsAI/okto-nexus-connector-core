import asyncio
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, ExecutionContext
from nexus_connector_core.native_action_bridge import (
    ContextGet, HandoffClaim, HandoffComplete, NativeActionGrant,
    ScopedNativeActionBridge,
)


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def wall_time(self):
        return self.now


class Backend:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.fail_read = False

    async def get_context(self, request, context):
        self.calls.append(("get", request, context))
        if self.fail_read:
            raise RuntimeError("read backend unavailable")
        return {"handoff_id": request.handoff_id, "status": "CLAIMED"}

    async def claim_handoff(self, request, context):
        self.calls.append(("claim", request, context))
        if self.fail:
            raise RuntimeError("lost canonical backend reply")
        return {"handoff_id": request.handoff_id, "claim_epoch": 1}

    async def complete_handoff(self, request, context):
        self.calls.append(("complete", request, context))
        return {"handoff_id": request.handoff_id, "status": "COMPLETED"}


def context():
    return ExecutionContext("srv", "exe", "bind", "agent", "ws", 4, 5, 6,
                            160.0, frozenset({"handoff.get", "handoff.claim",
                                              "handoff.complete"}))


def grant():
    return NativeActionGrant("native-cap:session", "srv", "exe", "bind",
                             "agent", "ws", "session", 6, 4, 5, 150.0,
                             frozenset({"handoff.get", "handoff.claim",
                                        "handoff.complete"}))


def test_scoped_actions_delegate_only_to_injected_canonical_backend():
    async def run():
        backend = Backend()
        bridge = ScopedNativeActionBridge(backend, grant(), clock=Clock())
        base = ("operation", "session", "native-cap:session", "handoff")
        assert (await bridge.invoke(ContextGet(*base), context()))["status"] == "CLAIMED"
        assert (await bridge.invoke(HandoffClaim(*base, "idempotency-1"),
                                    context()))["claim_epoch"] == 1
        assert (await bridge.invoke(HandoffComplete(*base, 1, {"summary": "done"}),
                                    context()))["status"] == "COMPLETED"
        assert [call[0] for call in backend.calls] == ["get", "claim", "complete"]
        assert all(call[2].agent_id == "agent" for call in backend.calls)

    asyncio.run(run())


def test_scope_revision_lease_and_capability_fail_before_backend():
    async def run():
        backend = Backend()
        clock = Clock()
        bridge = ScopedNativeActionBridge(backend, grant(), clock=clock)
        request = ContextGet("op", "session", "native-cap:session", "handoff")
        for bad in (replace(request, session_id="other"),
                    replace(request, capability_ref="native-cap:other")):
            with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
                await bridge.invoke(bad, context())
        for bad_context in (replace(context(), agent_id="other"),
                            replace(context(), connection_generation=7),
                            replace(context(), authorization_revision=5),
                            replace(context(), allowed_actions=frozenset())):
            with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
                await bridge.invoke(request, bad_context)
        clock.now = 150.0
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await bridge.invoke(request, context())
        assert backend.calls == []

    asyncio.run(run())


def test_native_action_grant_does_not_revive_after_clock_rollback():
    async def run():
        backend = Backend()
        clock = Clock()
        bridge = ScopedNativeActionBridge(backend, grant(), clock=clock)
        request = ContextGet("op", "session", "native-cap:session", "handoff")
        await bridge.invoke(request, context())
        clock.now = 99.0
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await bridge.invoke(request, context())
        clock.now = 110.0
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await bridge.invoke(request, context())
        assert [call[0] for call in backend.calls] == ["get"]

    asyncio.run(run())


def test_no_generic_mcp_envelope_or_unbounded_complete_result():
    async def run():
        backend = Backend()
        bridge = ScopedNativeActionBridge(backend, grant(), clock=Clock())
        base = ("op", "session", "native-cap:session", "handoff")
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
            await bridge.invoke({"jsonrpc": "2.0", "method": "tools/call"},
                                context())
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
            await bridge.invoke(HandoffComplete(*base, 1,
                                                {"jsonrpc": "2.0"}), context())
        with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
            await bridge.invoke(HandoffComplete(*base, 1, "x" * 17000), context())
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            await bridge.invoke(HandoffClaim(*base, "key", claim_epoch=True), context())
        assert backend.calls == []

    asyncio.run(run())


def test_backend_lost_reply_is_unknown_not_safe_retry():
    async def run():
        backend = Backend()
        backend.fail = True
        bridge = ScopedNativeActionBridge(backend, grant(), clock=Clock())
        request = HandoffClaim("op", "session", "native-cap:session", "handoff",
                               "idempotency-1")
        with pytest.raises(CoreError, match="OUTCOME_UNKNOWN") as exc:
            await bridge.invoke(request, context())
        assert exc.value.possible_effect and not exc.value.retry_safe
        assert exc.value.operation_id == "op"
        assert len(backend.calls) == 1

    asyncio.run(run())


def test_context_read_failure_is_safe_to_retry():
    async def run():
        backend = Backend()
        backend.fail_read = True
        bridge = ScopedNativeActionBridge(backend, grant(), clock=Clock())
        request = ContextGet("op", "session", "native-cap:session", "handoff")
        with pytest.raises(CoreError, match="EXECUTOR_OFFLINE") as exc:
            await bridge.invoke(request, context())
        assert exc.value.retry_safe and not exc.value.possible_effect

    asyncio.run(run())


def test_grant_requires_native_namespace_and_finite_expiry():
    for bad in (replace(grant(), capability_ref="mcp-cap:wrong"),
                replace(grant(), expires_monotonic=float("nan"))):
        with pytest.raises(ValueError):
            ScopedNativeActionBridge(Backend(), bad)
