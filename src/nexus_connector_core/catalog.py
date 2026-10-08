"""Public runtime catalog (C9/C01): the single source for consumers.

The authoritative adapter registry lives in ``native.registry`` (with
its module/class loading details). This module publishes a SAFE
PROJECTION of that single source as typed, immutable DTOs: consumers
enumerate what this Core build knows - what each adapter IS - without
importing ``native.*``, spawning processes, opening journals or holding
credentials.

Three concepts stay separated (the plan's contract):
1. CATALOG (here): which adapters this Core knows + public metadata.
2. LOCAL AVAILABILITY (``runtime.discover``/inventory): which candidates
   are installed/trusted/qualified on THIS host - produced where the
   harnesses live, never inferred from another host's OS.
3. BINDING ELIGIBILITY: availability plus the agent's permissions and
   policies - applied by the Nexus Server. The Core never grants
   canonical identity.

``READY``-style states do NOT appear here: a registered adapter is not
an available one, and an installed one is not a qualified one. Only managed
connections are supported; external-session attach has been removed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .native.registry import adapter_specs, adapter_spec, registered_managed_contract
from .models import ControlTargeting

#: Bumped when the projection's SHAPE changes; values themselves derive
#: from the single registry source on every call.
CATALOG_FORMAT_VERSION = 2

_SUPPORT_STATUS = {
    # managed adapters: implemented and eligible for the normal
    # qualification pipeline (qualification itself is per build/host).
    "codex_app_server": "managed_supported",
    "pi_rpc": "managed_supported",
    "claude_stream": "managed_supported",
}

_DISPLAY_NAMES = {
    "codex_app_server": "Codex (app-server)",
    "pi_rpc": "Pi (Node RPC)",
    "claude_stream": "Claude Code (stream)",
}

_HARNESS_FAMILIES = {
    "codex": "codex",
    "pi": "pi",
    "claude_code": "claude_code",
}


@dataclass(frozen=True, slots=True)
class RuntimeDescriptor:
    """Public, path-free metadata for ONE adapter known to this Core.

    Deliberately excludes the registry's module/class names: those are
    loading details, not a remote contract. Stable ordering comes from
    the catalog tuple (registry insertion order, deterministic).
    """

    adapter_id: str
    display_name: str
    harness_family: str
    native_kind: str
    connection_mode: str  # "managed" | "attach"
    #: Platforms the IMPLEMENTATION covers - not containment/provider
    #: qualification evidence for any of them.
    implementation_platforms: tuple[str, ...]
    support_status: str  # "managed_supported" | "registered_unqualified"
    #: Whether this adapter participates in PATH discovery (managed
    #: executables). Attach needs an explicit target and never
    #: path-scans.
    discoverable: bool
    control_targeting: tuple[ControlTargeting, ...]


@dataclass(frozen=True, slots=True)
class RuntimeCatalog:
    """The projection consumers enumerate; cheap, sync, side-effect-free."""

    core_version: str
    format_version: int
    runtimes: tuple[RuntimeDescriptor, ...]


def get_runtime_catalog() -> RuntimeCatalog:
    """Enumerate the runtimes this Core build knows (single source).

    Derived live from the adapter registry - adding an adapter there
    updates every consumer without touching Server/Connector/UI arrays.
    """
    from . import __version__
    descriptors = []
    for spec in adapter_specs():
        descriptors.append(RuntimeDescriptor(
            adapter_id=spec.adapter_id,
            display_name=_DISPLAY_NAMES.get(spec.adapter_id,
                                            spec.adapter_id),
            harness_family=_HARNESS_FAMILIES.get(spec.native_kind,
                                                 spec.native_kind),
            native_kind=spec.native_kind,
            connection_mode=spec.mode,
            implementation_platforms=tuple(sorted(spec.platforms)),
            support_status=_SUPPORT_STATUS.get(spec.adapter_id,
                'managed_supported' if spec.managed_contract == 1 else "registered_unqualified"),
            discoverable=(spec.mode == "managed"
                          and spec.executable_name is not None),
            control_targeting=spec.control_targeting,
        ))
    return RuntimeCatalog(
        core_version=__version__,
        format_version=CATALOG_FORMAT_VERSION,
        runtimes=tuple(descriptors),
    )


def get_runtime_connection_contract(adapter_id):
    """Path-free host integration metadata from trusted registration.

    This describes the implemented interface, not observed readiness. Another
    managed connector must independently confirm its version at opening.
    """
    registered = registered_managed_contract(adapter_id, check_platform=False)
    if registered is not None:
        return dict(managed_contract=1, tool_transport='none',
            transport_binding_contract=registered.transport_binding_contract)
    return dict(managed_contract=None, tool_transport='native' if adapter_id == 'pi_rpc' else 'mcp',
        transport_binding_contract=1 if adapter_id in _SUPPORT_STATUS else None)


__all__ = ["RuntimeDescriptor", "RuntimeCatalog", "get_runtime_catalog",
           "CATALOG_FORMAT_VERSION", "get_runtime_connection_contract"]
