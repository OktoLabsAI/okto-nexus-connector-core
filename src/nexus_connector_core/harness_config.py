"""Declarative direct HTTP client configuration. No MCP implementation lives here."""

from __future__ import annotations

import ipaddress
import hashlib
import json
import re
from dataclasses import dataclass, field
from collections.abc import Collection
from urllib.parse import urlsplit

from .models import CoreError


@dataclass(frozen=True, slots=True)
class DirectHTTPClientConfig:
    server_url: str
    capability_ref: str = field(repr=False)
    approved_origin: str
    transport: str = "streamable_http"


@dataclass(frozen=True, slots=True)
class HarnessHTTPTemplate:
    """Declarative client entry; the trusted host resolves the opaque ref."""

    adapter_id: str
    section: str
    entry_name: str
    server_url: str
    bearer_env_name: str
    capability_ref: str = field(repr=False)
    always_allow_tools: bool = False

    def entry(self) -> dict[str, object]:
        if self.adapter_id == "codex_app_server":
            return {"url": self.server_url,
                    "bearer_token_env_var": self.bearer_env_name,
                    **({"default_tools_approval_mode": "approve"} if self.always_allow_tools else {})}
        return {"type": "http", "url": self.server_url,
                "headers": {"Authorization":
                            f"Bearer ${{{self.bearer_env_name}}}"}}

    def environment_refs(self) -> dict[str, str]:
        return {self.bearer_env_name: self.capability_ref}


_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z", re.ASCII)


def _token_env_name(capability_ref: str) -> str:
    if not isinstance(capability_ref, str) or not _REF.fullmatch(capability_ref):
        raise CoreError("PROVIDER_AUTH_REQUIRED", "mcp_client_configuration")
    suffix = hashlib.sha256(capability_ref.encode("ascii")).hexdigest()[:16].upper()
    return f"NEXUS_MCP_TOKEN_{suffix}"


def _origin(url: str) -> tuple[str, bool]:
    # urlsplit strips some controls on its own. Reject them before parsing so
    # the approved URL is exactly the URL later given to the harness.
    if (not isinstance(url, str) or not url.isascii() or
            any(ord(char) <= 0x20 or ord(char) == 0x7f for char in url) or
            "\\" in url):
        raise CoreError("PROFILE_DRIFT", "mcp_client_configuration")
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise CoreError("PROFILE_DRIFT", "mcp_client_configuration") from exc
    if (parts.scheme not in ("http", "https") or not hostname or
            "@" in parts.netloc or "%" in hostname or
            parts.username or parts.password or parts.query or parts.fragment or
            not parts.path.startswith("/") or not parts.path.strip("/") or
            (port is not None and port == 0)):
        raise CoreError("PROFILE_DRIFT", "mcp_client_configuration")
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        # Some resolvers interpret non-canonical all-numeric hosts as IPv4.
        # Do not let one bypass the loopback rule by looking like a DNS name.
        if re.fullmatch(r"[0-9.]+", hostname) or hostname.lower().startswith("0x"):
            raise CoreError("PROFILE_DRIFT", "mcp_client_configuration")
        loopback = hostname.lower().rstrip(".") == "localhost"
    host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
    return f"{parts.scheme}://{host}{':' + str(port) if port is not None else ''}", loopback


def direct_http_config(server_url: str, capability_ref: str, *,
                       harness_is_local: bool, supports_http: bool,
                       approved_origins: Collection[str] | None,
                       loopback_reachable: bool = False) -> DirectHTTPClientConfig:
    if not supports_http:
        raise CoreError("CAPABILITY_UNSUPPORTED", "mcp_client_configuration")
    origin, loopback = _origin(server_url)
    if (approved_origins is None or isinstance(approved_origins, str) or
            origin not in approved_origins):
        raise CoreError("BINDING_NOT_AUTHORIZED", "mcp_client_configuration")
    if origin.startswith("http://") and not (harness_is_local and loopback
                                             and loopback_reachable):
        raise CoreError("PROFILE_DRIFT", "mcp_client_configuration")
    if loopback and not (harness_is_local and loopback_reachable):
        raise CoreError("WORKSPACE_UNAVAILABLE", "mcp_client_configuration")
    if not isinstance(capability_ref, str) or not _REF.fullmatch(capability_ref):
        raise CoreError("PROVIDER_AUTH_REQUIRED", "mcp_client_configuration")
    return DirectHTTPClientConfig(server_url, capability_ref, origin)


def harness_http_template(adapter_id: str, server_url: str,
                          capability_ref: str, *, entry_name: str,
                          harness_is_local: bool,
                          approved_origins: Collection[str] | None,
                          loopback_reachable: bool = False,
                          format_qualified: bool = False,
                          always_allow_tools: bool = False) -> HarnessHTTPTemplate:
    """Plan a native client's direct HTTP entry without a token or proxy.

    ``format_qualified`` is a trusted host assertion about the selected
    native build, not a value received from the Server/model. Pi has no
    built-in MCP HTTP client and cannot use this template.
    """
    if type(always_allow_tools) is not bool:
        raise CoreError("VALIDATION_ERROR", "mcp_client_configuration")
    if adapter_id not in {"codex_app_server", "claude_stream"} or format_qualified is not True:
        raise CoreError("CAPABILITY_UNSUPPORTED", "mcp_client_configuration")
    if not isinstance(entry_name, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]{0,63}", entry_name, re.ASCII):
        raise CoreError("VALIDATION_ERROR", "mcp_client_configuration")
    config = direct_http_config(
        server_url, capability_ref, harness_is_local=harness_is_local,
        supports_http=True, approved_origins=approved_origins,
        loopback_reachable=loopback_reachable)
    if not capability_ref.startswith("mcp-cap:") or len(capability_ref) <= len("mcp-cap:"):
        raise CoreError("BINDING_NOT_AUTHORIZED", "mcp_client_configuration")
    env_name = _token_env_name(capability_ref)
    section = "mcp_servers" if adapter_id == "codex_app_server" else "mcpServers"
    return HarnessHTTPTemplate(adapter_id, section, entry_name,
                               config.server_url, env_name, capability_ref, always_allow_tools)


def render_codex_toml_fragment(template: HarnessHTTPTemplate) -> str:
    """Render a parseable fragment, not an editor for existing TOML files."""
    if template.adapter_id != "codex_app_server":
        raise CoreError("CAPABILITY_UNSUPPORTED", "mcp_client_configuration")
    return (f"[mcp_servers.{template.entry_name}]\n"
            f"url = {json.dumps(template.server_url)}\n"
            f"bearer_token_env_var = {json.dumps(template.bearer_env_name)}\n" +
            ('default_tools_approval_mode = "approve"\n' if template.always_allow_tools else ''))


def process_http_arguments(adapter_id: str, templates, approved_refs) -> tuple[str, ...]:
    """Render bounded process-only MCP options without bearer material.

    The host supplies validated templates, never arbitrary argv or a config
    pathname from an execution request. Existing provider login stays in HOME.
    """
    if adapter_id not in ('codex_app_server', 'claude_stream'):
        raise CoreError('CAPABILITY_UNSUPPORTED', 'mcp_client_configuration')
    if type(templates) is not tuple or not 1 <= len(templates) <= 8:
        raise CoreError('VALIDATION_ERROR', 'mcp_client_configuration')
    entries = {}
    for template in templates:
        if (type(template) is not HarnessHTTPTemplate or template.adapter_id != adapter_id
                or type(template.always_allow_tools) is not bool
                or template.section != ('mcp_servers' if adapter_id == 'codex_app_server' else 'mcpServers')
                or type(template.entry_name) is not str
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', template.entry_name, re.ASCII)
                or template.entry_name in entries or template.capability_ref not in approved_refs
                or not template.capability_ref.startswith('mcp-cap:')
                or template.bearer_env_name != _token_env_name(template.capability_ref)
                or type(template.server_url) is not str or len(template.server_url) > 2048):
            raise CoreError('BINDING_NOT_AUTHORIZED', 'mcp_client_configuration')
        origin, loopback = _origin(template.server_url)
        if origin.startswith('http://') and not loopback:
            raise CoreError('PROFILE_DRIFT', 'mcp_client_configuration')
        entries[template.entry_name] = template.entry()
    if adapter_id == 'claude_stream':
        return ('--strict-mcp-config', '--mcp-config',
                json.dumps({'mcpServers': entries}, separators=(',', ':')),
                *(('--allowedTools', ','.join('mcp__'+t.entry_name+'__*' for t in templates if t.always_allow_tools))
                  if any(t.always_allow_tools for t in templates) else ()))
    fields = ','.join(json.dumps(name) + '={' + ','.join(
        key + '=' + json.dumps(value) for key, value in entry.items()) + '}'
        for name, entry in entries.items())
    return ('-c', 'mcp_servers={' + fields + '}')
