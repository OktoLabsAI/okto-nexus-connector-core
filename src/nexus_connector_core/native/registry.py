"""Trusted, metadata-first registry for Core-owned native adapters.

Only entries in this static table may be loaded. Network data may select an
adapter ID, never a module name, class name, or executable factory.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import sys
from typing import Any

from ..models import CoreError, ControlTargeting


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    adapter_id: str
    native_kind: str
    module: str
    class_name: str
    mode: str
    executable_name: str | None
    platforms: frozenset[str]
    control_targeting: tuple[ControlTargeting, ...]
    # Optional contract for another trusted, locally installed connector. The
    # module/class still come exclusively from this registry, never a request.
    managed_contract: int | None = None
    launch_arguments: tuple[str, ...] = ()
    transport_binding_contract: int | None = None
    context_observation_contract: int | None = None


_SPECS = {
    "codex_app_server": AdapterSpec(
        "codex_app_server", "codex", ".adapters.codex",
        "CodexAppServerConnector", "managed", "codex",
        frozenset({"win32", "linux", "darwin"}),
        (ControlTargeting("turn.steer", True, "required", True, "IMMEDIATE"),
         ControlTargeting("turn.interrupt", True, "optional", True))),
    "pi_rpc": AdapterSpec(
        "pi_rpc", "pi", ".adapters.pi", "PiRpcConnector", "managed", "pi",
        frozenset({"win32", "linux", "darwin"}),
        (ControlTargeting("turn.steer", True, "forbidden", True, "NEXT_TURN_BOUNDARY"),
         ControlTargeting("turn.interrupt", True, "forbidden", True))),
    "claude_stream": AdapterSpec(
        "claude_stream", "claude_code", ".adapters.claude_code_stream",
        "ClaudeCodeStreamConnector", "managed", "claude",
        frozenset({"win32", "linux", "darwin"}),
        (ControlTargeting("turn.steer", True, "forbidden", True, "IMMEDIATE"),
         ControlTargeting("turn.interrupt", True, "forbidden", True))),

}


def adapter_specs() -> tuple[AdapterSpec, ...]:
    """Return immutable metadata without importing an adapter module."""
    return tuple(_SPECS.values())


def adapter_spec(adapter_id: str, *, platform: str | None = None) -> AdapterSpec:
    if not isinstance(adapter_id, str) or adapter_id not in _SPECS:
        raise CoreError("CAPABILITY_UNSUPPORTED", "adapter_registry")
    spec = _SPECS[adapter_id]
    host_platform = platform or sys.platform
    if host_platform.startswith("freebsd"):
        host_platform = "freebsd"
    if host_platform not in spec.platforms:
        raise CoreError("NATIVE_PLATFORM_UNSUPPORTED", "adapter_registry")
    return spec


def load_adapter(adapter_id: str, *, platform: str | None = None) -> type[Any]:
    """Lazy-load only a statically named class after ID/platform checks."""
    spec = adapter_spec(adapter_id, platform=platform)
    try:
        module = import_module(spec.module, package="nexus_connector_core.native")
        connector = getattr(module, spec.class_name)
    except (ImportError, AttributeError) as exc:
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "adapter_registry") from exc
    if not isinstance(connector, type):
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "adapter_registry")
    return connector


def registered_managed_contract(adapter_id: str, *, check_platform=True) -> AdapterSpec | None:
    spec = adapter_spec(adapter_id) if check_platform else _SPECS.get(adapter_id)
    if spec is None:
        raise CoreError('CAPABILITY_UNSUPPORTED', 'adapter_registry')
    if spec.managed_contract is None:
        return None
    if (type(spec.managed_contract) is not int or spec.managed_contract != 1
            or spec.mode != 'managed' or type(spec.launch_arguments) is not tuple
            or (spec.transport_binding_contract is not None and
                (type(spec.transport_binding_contract) is not int or spec.transport_binding_contract < 1))
            or any(type(arg) is not str or '\x00' in arg for arg in spec.launch_arguments)):
        raise CoreError('CAPABILITY_UNSUPPORTED', 'adapter_registry')
    return spec
