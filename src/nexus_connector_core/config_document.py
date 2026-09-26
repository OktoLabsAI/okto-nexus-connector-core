"""Pure structural planning/CAS for explicitly selected harness config.

The host owns file selection, consent, secure backup and atomic persistence.
This module never reads a path or writes a file, so a remote intention cannot
turn it into an arbitrary filesystem editor.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import CoreError
from .protocol import canonical_json, strict_json
from .harness_config import HarnessHTTPTemplate, render_codex_toml_fragment

_MAX_CONFIG_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class JsonConfigPlan:
    section: str
    entry_name: str
    expected_sha256: str | None
    changed: bool
    changed_fields: tuple[str, ...]
    _replacement: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class TomlConfigPlan:
    entry_name: str
    expected_sha256: str | None
    changed: bool
    changed_fields: tuple[str, ...]
    _replacement: bytes = field(repr=False)


def _digest(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _parse(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {}
    if len(data) > _MAX_CONFIG_BYTES:
        raise CoreError("CAPACITY_EXCEEDED", "config_plan")
    try:
        parsed = strict_json(data.decode("utf-8", errors="strict"))
        canonical_json(parsed)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CoreError("PROFILE_DRIFT", "config_plan") from exc
    if not isinstance(parsed, dict):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    return parsed


def plan_json_entry(document: bytes | None, *, section: str, entry_name: str,
                    proposed: Mapping[str, Any],
                    previously_owned: Mapping[str, Any] | None = None) -> JsonConfigPlan:
    """Plan one entry; existing entries need an exact owner-known predecessor.

    ``previously_owned`` must come from trusted host ownership state, never
    from the untrusted document being edited. A missing or conflicting entry
    fails closed rather than claiming ownership from its name or appearance.
    """
    if (not section or not entry_name or not isinstance(section, str) or
            not isinstance(entry_name, str) or not isinstance(proposed, Mapping)):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    try:
        canonical_json({section: {entry_name: None}})
    except ValueError as exc:
        raise CoreError("PROFILE_DRIFT", "config_plan") from exc
    source = _parse(document)
    current_section = source.get(section, {})
    if not isinstance(current_section, dict):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    current = current_section.get(entry_name)
    exists = entry_name in current_section
    if exists and previously_owned is None:
        raise CoreError("APPROVAL_REQUIRED", "config_plan")
    try:
        if previously_owned is not None and (not exists or
                canonical_json(current) != canonical_json(dict(previously_owned))):
            raise CoreError("PROFILE_DRIFT", "config_plan")
        # Validate before merge; round-trip gives the plan an immutable JSON
        # snapshot even if the caller later mutates the input mapping.
        new_entry = json.loads(canonical_json(dict(proposed)))
    except (ValueError, TypeError) as exc:
        raise CoreError("PROFILE_DRIFT", "config_plan") from exc
    try:
        if exists and canonical_json(current) == canonical_json(new_entry):
            return JsonConfigPlan(section, entry_name, _digest(document), False, (),
                                  document if document is not None else b"{}\n")
        old_fields = current if isinstance(current, dict) else {}
        changed_fields = tuple(sorted(
            key for key in old_fields.keys() | new_entry.keys()
            if key not in old_fields or key not in new_entry or
            canonical_json(old_fields[key]) != canonical_json(new_entry[key])
        ))
    except ValueError as exc:
        raise CoreError("PROFILE_DRIFT", "config_plan") from exc
    current_section[entry_name] = new_entry
    source[section] = current_section
    try:
        canonical_json(source)
        replacement = (json.dumps(source, ensure_ascii=False, indent=2,
                                  allow_nan=False) + "\n").encode("utf-8")
    except ValueError as exc:
        raise CoreError("PROFILE_DRIFT", "config_plan") from exc
    if len(replacement) > _MAX_CONFIG_BYTES:
        raise CoreError("CAPACITY_EXCEEDED", "config_plan")
    return JsonConfigPlan(section, entry_name, _digest(document), True,
                          changed_fields,
                          replacement)


def plan_json_entry_removal(document: bytes | None, *, section: str,
                            entry_name: str,
                            previously_owned: Mapping[str, Any]) -> JsonConfigPlan:
    """Remove only an exactly owned entry, leaving other configuration intact."""
    if (not isinstance(section, str) or not section or
            not isinstance(entry_name, str) or not entry_name or
            not isinstance(previously_owned, Mapping)):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    source = _parse(document)
    current_section = source.get(section)
    if not isinstance(current_section, dict) or entry_name not in current_section:
        raise CoreError("PROFILE_DRIFT", "config_plan")
    try:
        if (canonical_json(current_section[entry_name]) !=
                canonical_json(dict(previously_owned))):
            raise CoreError("PROFILE_DRIFT", "config_plan")
        changed_fields = tuple(sorted(previously_owned))
        del current_section[entry_name]
        replacement = (json.dumps(source, ensure_ascii=False, indent=2,
                                  allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise CoreError("PROFILE_DRIFT", "config_plan") from exc
    if len(replacement) > _MAX_CONFIG_BYTES:
        raise CoreError("CAPACITY_EXCEEDED", "config_plan")
    return JsonConfigPlan(section, entry_name, _digest(document), True,
                          changed_fields, replacement)


def apply_json_plan(plan: JsonConfigPlan, latest_document: bytes | None) -> bytes:
    """Check source revision and return bytes for a host's atomic commit.

    This is an optimistic in-memory CAS check. The host must repeat the
    comparison under its filesystem lock before replacing the file, and make
    a secure backup; this function alone is not a durable file transaction.
    """
    if _digest(latest_document) != plan.expected_sha256:
        raise CoreError("PROFILE_DRIFT", "config_apply")
    return plan._replacement


_CODEX_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z", re.ASCII)


def _parse_toml(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {}
    if len(data) > _MAX_CONFIG_BYTES:
        raise CoreError("CAPACITY_EXCEEDED", "config_plan")
    try:
        parsed = tomllib.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CoreError("PROFILE_DRIFT", "config_plan") from exc
    return parsed


def _codex_servers(parsed: dict[str, Any]) -> dict[str, Any]:
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    return servers


def _owned_toml_span(document: bytes, entry_name: str) -> tuple[int, int]:
    """Locate a simple owned table; complex/ambiguous TOML fails closed."""
    lines = document.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    header = f"[mcp_servers.{entry_name}]".encode("ascii")
    matches = [index for index, line in enumerate(lines) if line.strip() == header]
    if len(matches) != 1:
        raise CoreError("PROFILE_DRIFT", "config_plan")
    start = matches[0]
    end = start + 1
    while end < len(lines) and not lines[end].lstrip().startswith(b"["):
        line = lines[end].strip()
        if line and (b"#" in line or not re.match(
                rb"(?:url|bearer_token_env_var)[ \t]*=", line)):
            raise CoreError("PROFILE_DRIFT", "config_plan")
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return offsets[start], offsets[end]


def _check_toml_result(replacement: bytes, expected: dict[str, Any]) -> None:
    if len(replacement) > _MAX_CONFIG_BYTES:
        raise CoreError("CAPACITY_EXCEEDED", "config_plan")
    if _parse_toml(replacement) != expected:
        raise CoreError("PROFILE_DRIFT", "config_plan")


def plan_codex_toml_entry(
        document: bytes | None, template: HarnessHTTPTemplate, *,
        previously_owned: Mapping[str, Any] | None = None) -> TomlConfigPlan:
    """Plan a direct-HTTP Codex entry without rewriting third-party TOML."""
    if template.adapter_id != "codex_app_server":
        raise CoreError("CAPABILITY_UNSUPPORTED", "config_plan")
    if (template.section != "mcp_servers" or
            not isinstance(template.entry_name, str) or
            not _CODEX_NAME.fullmatch(template.entry_name)):
        raise CoreError("VALIDATION_ERROR", "config_plan")
    parsed = _parse_toml(document)
    servers = _codex_servers(parsed)
    name = template.entry_name
    proposed = template.entry()
    exists = name in servers
    if exists and previously_owned is None:
        raise CoreError("APPROVAL_REQUIRED", "config_plan")
    if previously_owned is not None and (not exists or
            servers[name] != dict(previously_owned)):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    if exists and servers[name] == proposed:
        return TomlConfigPlan(name, _digest(document), False, (), document or b"")
    old = servers[name] if exists else {}
    changed_fields = tuple(sorted(key for key in old.keys() | proposed.keys()
                                  if old.get(key) != proposed.get(key)))
    source = document or b""
    newline = (b"\r\n" if b"\r\n" in source and
               b"\n" not in source.replace(b"\r\n", b"") else b"\n")
    fragment = render_codex_toml_fragment(template).encode("utf-8").replace(
        b"\n", newline)
    if exists:
        assert document is not None
        start, end = _owned_toml_span(document, name)
        replacement = document[:start] + fragment + document[end:]
    else:
        separator = b"" if not source else (newline if source.endswith(b"\n")
                                               else newline + newline)
        replacement = source + separator + fragment
    expected = deepcopy(parsed)
    expected.setdefault("mcp_servers", {})[name] = proposed
    _check_toml_result(replacement, expected)
    return TomlConfigPlan(name, _digest(document), True, changed_fields, replacement)


def plan_codex_toml_entry_removal(
        document: bytes | None, *, entry_name: str,
        previously_owned: Mapping[str, Any]) -> TomlConfigPlan:
    """Remove only an exactly owned, simple Codex MCP table."""
    if not isinstance(entry_name, str) or not _CODEX_NAME.fullmatch(entry_name):
        raise CoreError("VALIDATION_ERROR", "config_plan")
    if not isinstance(previously_owned, Mapping):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    parsed = _parse_toml(document)
    servers = _codex_servers(parsed)
    if entry_name not in servers or servers[entry_name] != dict(previously_owned):
        raise CoreError("PROFILE_DRIFT", "config_plan")
    assert document is not None
    start, end = _owned_toml_span(document, entry_name)
    replacement = document[:start] + document[end:]
    expected = deepcopy(parsed)
    del expected["mcp_servers"][entry_name]
    if not expected["mcp_servers"]:
        del expected["mcp_servers"]
    _check_toml_result(replacement, expected)
    return TomlConfigPlan(entry_name, _digest(document), True,
                          tuple(sorted(previously_owned)), replacement)


def apply_toml_plan(plan: TomlConfigPlan, latest_document: bytes | None) -> bytes:
    """Check the exact source revision before a trusted host commits the plan."""
    if _digest(latest_document) != plan.expected_sha256:
        raise CoreError("PROFILE_DRIFT", "config_apply")
    return plan._replacement
