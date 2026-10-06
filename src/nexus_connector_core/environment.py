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

# USER/LOGNAME are account identity, not secrets: Claude Code keys its macOS
# Keychain login on $USER and reports "Not logged in" without it.
_ESSENTIALS = frozenset({"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                         "PATH", "TEMP", "TMP", "LANG", "LC_ALL", "TERM",
                         "USER", "LOGNAME"})
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
        if prepared.intent.adapter_id == "pi_rpc":
            # The approved Pi provider directory contains settings/auth directly;
            # HOME alone would make Pi append .pi/agent a second time.
            env["PI_CODING_AGENT_DIR"] = env["HOME"]
        if prepared.intent.adapter_id == "claude_stream":
            if _is_default_claude_state(home):
                # The account's own ~/.claude: keep the real HOME and leave
                # CLAUDE_CONFIG_DIR unset. Either redirect makes Claude Code
                # look up a different macOS Keychain entry and global config.
                env["HOME"] = str(Path(env["HOME"]).parent)
                env["USERPROFILE"] = env["HOME"]
            else:
                # Preserve legacy user-home configurations as well as exact state dirs.
                claude_state = home / '.claude' if (home / '.claude').is_dir() else home
                env["CLAUDE_CONFIG_DIR"] = str(claude_state.resolve(strict=True))
        if prepared.intent.adapter_id == "codex_app_server":
            # Codex may resolve the Windows account home independently of HOME
            # and USERPROFILE. Bind its state to the explicitly approved home.
            from .provider_discovery import discover_provider_home
            direct_state = (home.name == '.codex' or (home / 'auth.json').is_file() or
                            (home / 'config.toml').is_file() or
                            str(home.resolve(strict=True)) == discover_provider_home('codex_app_server'))
            codex_state = home if direct_state else home / ".codex"
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


def _is_default_claude_state(home: Path) -> bool:
    """True only for the host account's default Claude state directory."""
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return False
    try:
        default = Path.home() / ".claude"
        return (default.is_dir() and
                home.resolve(strict=True) == default.resolve(strict=True))
    except (OSError, RuntimeError):
        return False


def _check_name(name: str) -> None:
    if (not _NAME.fullmatch(name) or "NEXUS" in name.upper()
            or name.upper() in _RESTRICTED):
        raise CoreError("BINDING_NOT_AUTHORIZED", "environment")


def _check_value(value: str) -> None:
    if (not isinstance(value, str) or "\x00" in value
            or "nxs_" in value or "nxsept_" in value):
        raise CoreError("BINDING_NOT_AUTHORIZED", "environment")
