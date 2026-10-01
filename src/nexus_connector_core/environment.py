"""Minimal child environment assembled from local, explicit references."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from .models import CoreError, PreparedLaunch
from .ports import SecretResolver
from .harness_config import HarnessHTTPTemplate, _token_env_name

_ESSENTIALS = frozenset({"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                         "PATH", "TEMP", "TMP", "LANG", "LC_ALL", "TERM"})
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESTRICTED = frozenset({"HOME", "USERPROFILE", "CODEX_HOME",
                         "CLAUDE_CONFIG_DIR", "PI_CODING_AGENT_DIR",
                         "PATH", "PYTHONPATH", "PYTHONHOME"})


class ProcessHTTPEnvironment(Mapping[str, str]):
    """Host-only environment plus typed MCP configuration for this process.

    Values are immutable and omitted from repr. This object is not a wire DTO
    and is never persisted in a prepared launch or receipt.
    """
    def __init__(self, values, templates):
        self._values = MappingProxyType(dict(values))
        self.http_templates = tuple(templates)

    def __getitem__(self, name):
        return self._values[name]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return 'ProcessHTTPEnvironment(<protected>)'


async def child_environment(
    prepared: PreparedLaunch,
    resolver: SecretResolver,
    *,
    secret_bindings: Mapping[str, str] | None = None,
    http_templates: Sequence[HarnessHTTPTemplate] = (),
    public_overrides: Mapping[str, str] | None = None,
    provider_home: str | Path | None = None,
    trusted_home: bool = False,
    process_http: bool = False,
) -> Mapping[str, str]:
    """Resolve only the secret refs listed in ``prepared`` on this host.

    The returned mapping is for process creation only. Hosts must not put it in
    a receipt, NXL frame, event, log, or central persistence.
    """
    if type(process_http) is not bool:
        raise CoreError('VALIDATION_ERROR', 'mcp_client_configuration')
    if process_http:
        from .harness_config import process_http_arguments
        http_templates = tuple(http_templates)
        process_http_arguments(prepared.intent.adapter_id, http_templates, prepared.secret_refs)
    env = {name: value for name, value in os.environ.items()
           if name.upper() in _ESSENTIALS}
    if provider_home is not None:
        if not trusted_home:
            raise CoreError("APPROVAL_REQUIRED", "environment")
        home = Path(provider_home)
        if not home.is_absolute() or not home.is_dir():
            raise CoreError("WORKSPACE_UNAVAILABLE", "environment")
        env["HOME"] = str(home.resolve(strict=True))
        env["USERPROFILE"] = env["HOME"]
        if prepared.intent.adapter_id == "codex_app_server":
            # Codex may resolve the Windows account home independently of HOME
            # and USERPROFILE. Bind its state to the explicitly approved home.
            codex_state = Path(env["HOME"]) / ".codex"
            try:
                codex_state.mkdir(mode=0o700, exist_ok=True)
                env["CODEX_HOME"] = str(codex_state.resolve(strict=True))
            except OSError:
                raise CoreError("WORKSPACE_UNAVAILABLE", "environment") from None
    for name, value in (public_overrides or {}).items():
        _check_name(name)
        _check_value(value)
        env[name] = value
    approved = set(prepared.secret_refs)
    for name, reference in (secret_bindings or {}).items():
        _check_name(name)
        if reference not in approved:
            raise CoreError("BINDING_NOT_AUTHORIZED", "environment")
        value = await resolver.resolve(reference)
        _check_value(value)
        env[name] = value
    for template in http_templates:
        if not isinstance(template, HarnessHTTPTemplate):
            raise CoreError("BINDING_NOT_AUTHORIZED", "environment")
        reference = template.capability_ref
        name = template.bearer_env_name
        if (template.adapter_id != prepared.intent.adapter_id or
                reference not in approved or
                name != _token_env_name(reference) or name in env):
            raise CoreError("BINDING_NOT_AUTHORIZED", "environment")
        try:
            value = await resolver.resolve(reference)
        except Exception:
            raise CoreError("AGENT_AUTH_REQUIRED", "environment") from None
        if (not isinstance(value, str) or not value or "\x00" in value or
                "nxs_" in value or "nxsept_" in value):
            raise CoreError("AGENT_AUTH_REQUIRED", "environment")
        env[name] = value
    return ProcessHTTPEnvironment(env, http_templates) if process_http else env


def _check_name(name: str) -> None:
    if (not _NAME.fullmatch(name) or "NEXUS" in name.upper()
            or name.upper() in _RESTRICTED):
        raise CoreError("BINDING_NOT_AUTHORIZED", "environment")


def _check_value(value: str) -> None:
    if (not isinstance(value, str) or "\x00" in value
            or "nxs_" in value or "nxsept_" in value):
        raise CoreError("BINDING_NOT_AUTHORIZED", "environment")
