"""Supported runtime composition for both host applications (C1/PC06).

`create_runtime` is the public factory: Nexus Server (embedded) and
Nexus Connector (remote) instantiate the real runtime through this
function only - no private bridge imports, no provider protocol
knowledge. The Core still does no login, no WSS, no MCP and no canonical
identity: the host supplies authority, credentials and callbacks.
"""

from __future__ import annotations

from typing import Callable, Mapping, Awaitable, Optional

from .models import InstallationCandidate, PreparedLaunch
from .native.runtime_bridge import CopiedAdapterFactory
from .pi_extension_resource import PiNativeActionLaunch
from .runtime import LocalRuntimeCore

__all__ = ["create_runtime"]


def create_runtime(
    *,
    journal,
    environment: Callable[[PreparedLaunch], Awaitable[Mapping[str, str]]],
    candidates: Mapping[str, InstallationCandidate],
    workspace_roots: Mapping[str, str],
    native_factory=None,
    owned_slot_ledger=None,
    clock=None,
    event_sink=None,
    lease_grace_seconds: float = 15.0,
    lease_poll_seconds: float = 0.25,
    max_lease_seconds: float = 120.0,
    reconnect_fence_seconds: float = 5.0,
    max_concurrent_opens: int = 8,
    max_owned_sessions: int = 32,
    trusted_discovery_roots: tuple = (),
    pi_install_root=None,
    pi_node=None,
    codex_client_info: Optional[Mapping[str, str]] = None,
    codex_resume=None,
    pi_native_action=None,
    native_approvals_enabled: bool = False,
) -> LocalRuntimeCore:
    """Compose the real local runtime from typed, host-supplied inputs.

    Parameters
    ----------
    journal:
        The host's technical journal (the reference ``SQLiteJournal`` or a
        host adapter that passes the conformance kits). The Core never
        closes a journal it did not create.
    environment:
        Async callable resolving the approved per-launch environment
        overlay (essentials plus provider credential references). Runs on
        the host's trust; the Core only seals it.
    candidates / workspace_roots:
        Explicitly selected installations per adapter id and approved
        absolute workspace roots. Discovery never happens implicitly here.
    native_factory:
        Optional injection point for contract-level smokes (fake natives).
        Production hosts omit it and get the real copied-adapter factory;
        nothing private needs to be imported either way.
    owned_slot_ledger, clock, event_sink, budgets:
        Optional installation ledger, monotonic clock, durable-event sink
        and lifecycle budgets - all validated by the runtime constructor.
    codex_client_info / codex_resume / pi_native_action:
        Trusted-host callbacks: validated Codex client identity, the
        resume-grant seam and the scoped Pi native-action launch.
    native_approvals_enabled:
        Explicit opt-in for the native approval/input seam (off by
        default; requires both approval actions in every launch context).
    """
    if not callable(environment):
        raise TypeError("environment must be callable")
    if not isinstance(candidates, Mapping) or not candidates:
        raise TypeError("candidates must be a non-empty mapping")
    for adapter_id, candidate in candidates.items():
        if not isinstance(adapter_id, str) or not adapter_id:
            raise TypeError("candidate keys must be adapter ids")
        if not isinstance(candidate, InstallationCandidate):
            raise TypeError("candidates must contain InstallationCandidate")
    if not isinstance(workspace_roots, Mapping) or not workspace_roots:
        raise TypeError("workspace_roots must be a non-empty mapping")
    if type(native_approvals_enabled) is not bool:
        raise TypeError("native_approvals_enabled must be bool")
    for callback, name in ((codex_resume, "codex_resume"),
                           (pi_native_action, "pi_native_action")):
        if callback is not None and not callable(callback):
            raise TypeError(f"{name} must be callable when provided")
    if native_factory is None:
        # C3/S01: ONE effective temporal source shared by runtime, kernel
        # and factory - including the DEFAULT (no host clock provided).
        # An optional test parameter never disables protection: without it
        # the real system monotonic clock is used under the same contract.
        from .clock import SystemClock
        effective_clock = clock if clock is not None else SystemClock()
        native_factory = CopiedAdapterFactory(
            environment,
            pi_native_action=pi_native_action,
            codex_client_info=codex_client_info,
            codex_resume=codex_resume,
            native_approvals_enabled=native_approvals_enabled,
            clock=effective_clock.monotonic)
    else:
        effective_clock = clock
    return LocalRuntimeCore(
        journal, native_factory,
        candidates=dict(candidates),
        workspace_roots=dict(workspace_roots),
        owned_slot_ledger=owned_slot_ledger,
        trusted_discovery_roots=tuple(trusted_discovery_roots),
        pi_install_root=pi_install_root,
        pi_node=pi_node,
        clock=effective_clock,
        event_sink=event_sink,
        lease_grace_seconds=lease_grace_seconds,
        lease_poll_seconds=lease_poll_seconds,
        max_lease_seconds=max_lease_seconds,
        reconnect_fence_seconds=reconnect_fence_seconds,
        max_concurrent_opens=max_concurrent_opens,
        max_owned_sessions=max_owned_sessions)
