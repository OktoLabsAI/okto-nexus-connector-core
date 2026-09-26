"""Minimal child environment assembled from local, explicit references."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from .models import CoreError, PreparedLaunch
from .ports import SecretResolver
from .harness_config import HarnessHTTPTemplate, _token_env_name

_ESSENTIALS = frozenset({"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                         "PATH", "TEMP", "TMP", "LANG", "LC_ALL", "TERM"})
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESTRICTED = frozenset({"HOME", "USERPROFILE", "CODEX_HOME",
                         "CLAUDE_CONFIG_DIR", "PI_CODING_AGENT_DIR",
                         "PATH", "PYTHONPATH", "PYTHONHOME"})


async def child_environment(
    prepared: PreparedLaunch,
    resolver: SecretResolver,
    *,
    secret_bindings: Mapping[str, str] | None = None,
    http_templates: Sequence[HarnessHTTPTemplate] = (),
    public_overrides: Mapping[str, str] | None = None,
    provider_home: str | Path | None = None,
    trusted_home: bool = False,
) -> dict[str, str]:
    """Resolve only the secret refs listed in ``prepared`` on this host.

    The returned mapping is for process creation only. Hosts must not put it in
    a receipt, NXL frame, event, log, or central persistence.
    """
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
    return env


def _check_name(name: str) -> None:
    if (not _NAME.fullmatch(name) or "NEXUS" in name.upper()
            or name.upper() in _RESTRICTED):
        raise CoreError("BINDING_NOT_AUTHORIZED", "environment")


def _check_value(value: str) -> None:
    if (not isinstance(value, str) or "\x00" in value
            or "nxs_" in value or "nxsept_" in value):
        raise CoreError("BINDING_NOT_AUTHORIZED", "environment")
