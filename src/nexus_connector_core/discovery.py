"""Local executable discovery. No candidate is executed by this module."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import struct
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from .installation import installation_ref
from .models import CoreError, InstallationCandidate
from .native.process import require_containment
from .native.registry import adapter_specs
from .build_identity import (executable_build_identity,
                                pi_build_identity)
from .protocol import canonical_json

EXECUTABLE_NAMES = {spec.adapter_id: spec.executable_name
                    for spec in adapter_specs() if spec.executable_name is not None}

_PE_MACHINES = {0x014C: "x86", 0x8664: "x86_64", 0xAA64: "aarch64"}
_ELF_MACHINES = {3: "x86", 62: "x86_64", 183: "aarch64", 40: "arm"}
_MACH_MACHINES = {0x01000007: "x86_64", 0x0100000C: "aarch64"}
_PROBE_ENV = frozenset({"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                        "PATH", "TEMP", "TMP", "LANG", "LC_ALL", "TERM"})


def binary_architecture(path: str | Path) -> str | None:
    """Read only bounded executable headers; do not execute a candidate."""
    with Path(path).open("rb") as stream:
        head = stream.read(64)
        if len(head) >= 20 and head[:4] == b"\x7fELF":
            endian = {1: "<", 2: ">"}.get(head[5])
            if endian is None:
                return None
            return _ELF_MACHINES.get(struct.unpack(endian + "H", head[18:20])[0])
        if len(head) >= 64 and head[:2] == b"MZ":
            offset = struct.unpack("<I", head[60:64])[0]
            if offset > 1024 * 1024:
                return None
            stream.seek(offset)
            pe = stream.read(6)
            if len(pe) == 6 and pe[:4] == b"PE\x00\x00":
                return _PE_MACHINES.get(struct.unpack("<H", pe[4:6])[0])
            return None
        if len(head) >= 8:
            magic = head[:4]
            endian = ("<" if magic == b"\xcf\xfa\xed\xfe" else
                      ">" if magic == b"\xfe\xed\xfa\xcf" else None)
            if endian is not None:
                return _MACH_MACHINES.get(struct.unpack(endian + "I", head[4:8])[0])
    return None


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _pi_node_cli_fingerprint(node: Path, script: Path) -> str:
    identity = {"kind": "pi_node_cli_v1", "node": str(node),
                "node_sha256": fingerprint(node), "script": str(script),
                "script_sha256": fingerprint(script)}
    return "sha256:" + hashlib.sha256(canonical_json(identity)).hexdigest()


def _is_pi_package_cli(script: Path) -> bool:
    return (script.is_file() and tuple(script.parts[-6:]) ==
            ("node_modules", "@earendil-works", "pi-coding-agent",
             "dist", "bundle", "cli.js"))


def candidate_pi_node_cli(node_path: str | Path, script_path: str | Path, *,
                          explicit: bool = False,
                          trusted_roots: tuple[Path, ...] = ()) -> InstallationCandidate:
    """Select the Pi package CLI through an explicitly trusted Node binary.

    The shell launcher is never executed. The package path is fixed to the
    installed Pi CLI entry point; neither path comes from a remote intent.
    """
    node = candidate("pi_rpc", node_path, explicit=explicit,
                     trusted_roots=trusted_roots)
    requested = Path(script_path)
    if not requested.is_absolute():
        raise CoreError("BINARY_NOT_FOUND", "discovery")
    script = requested.resolve(strict=True)
    if not _is_pi_package_cli(script):
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
    if not explicit and not any(script.is_relative_to(root.resolve(strict=True))
                                for root in trusted_roots):
        raise CoreError("APPROVAL_REQUIRED", "discovery")
    # C2/R06: the hashed unit is the pi-coding-agent PACKAGE directory
    # (parents[2]); the @earendil-works scope directory would drag unrelated
    # sibling packages into the identity while missing declared deps
    # hoisted in node_modules (covered now via the dependency closure).
    package_root = script.parents[2]  # .../pi-coding-agent/dist/bundle/cli.js
    return replace(node,
                   fingerprint=_pi_node_cli_fingerprint(Path(node.executable), script),
                   launch_script=str(script),
                   version=_pi_package_version(package_root),
                   build_identity=pi_build_identity(node.executable, package_root),
                   # The selectable Pi installation is the (node, cli.js)
                   # target pair - the ref covers both canonical targets.
                   installation_ref=installation_ref(
                       "pi_rpc", node.executable, str(script)))


def _pi_package_version(package_root: Path) -> str | None:
    """Bounded read of the package's own declared version, if any."""
    import json
    try:
        data = json.loads(
            (package_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) and version else None


def selected_fingerprint(selected: InstallationCandidate) -> str:
    executable = Path(selected.executable).resolve(strict=True)
    if selected.launch_script is None:
        return fingerprint(executable)
    if selected.adapter_id != "pi_rpc":
        raise CoreError("BINDING_NOT_AUTHORIZED", "discovery")
    script = Path(selected.launch_script).resolve(strict=True)
    if not _is_pi_package_cli(script):
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
    return _pi_node_cli_fingerprint(executable, script)


def candidate(adapter_id: str, path: str | Path, *, explicit: bool = False,
              trusted_roots: tuple[Path, ...] = ()) -> InstallationCandidate:
    if adapter_id not in EXECUTABLE_NAMES:
        raise CoreError("CAPABILITY_UNSUPPORTED", "discovery")
    requested = Path(path)
    if not requested.is_absolute():
        raise CoreError("BINARY_NOT_FOUND", "discovery")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file():
        raise CoreError("BINARY_NOT_FOUND", "discovery")
    if os.name == "nt" and resolved.suffix.lower() not in (".exe", ".com"):
        # Batch/PowerShell wrappers require a command interpreter and a
        # separate, explicit trust design before they can be launched.
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
    if os.name != "nt" and not os.access(resolved, os.X_OK):
        raise CoreError("BINARY_NOT_FOUND", "discovery")
    roots = tuple(root.resolve(strict=True) for root in trusted_roots)
    trusted = explicit or any(resolved.is_relative_to(root) for root in roots)
    if not trusted:
        raise CoreError("APPROVAL_REQUIRED", "discovery")
    return InstallationCandidate(adapter_id, str(resolved), fingerprint(resolved),
                                 "explicit" if explicit else "trusted_root",
                                 "selected", architecture=binary_architecture(resolved),
                                 build_identity=executable_build_identity(resolved),
                                 installation_ref=installation_ref(
                                     adapter_id, str(resolved)))


async def probe_selected_claude(candidate: InstallationCandidate, *, cwd: str | Path,
                                env: Mapping[str, str]) -> InstallationCandidate:
    return await asyncio.to_thread(_probe_selected_version, candidate,
                                   "claude_stream", cwd=cwd, env=env)


async def probe_selected_pi(candidate: InstallationCandidate, *, cwd: str | Path,
                            env: Mapping[str, str]) -> InstallationCandidate:
    return await asyncio.to_thread(_probe_selected_version, candidate,
                                   "pi_rpc", cwd=cwd, env=env)


async def probe_selected_codex(candidate: InstallationCandidate, *, cwd: str | Path,
                               env: Mapping[str, str]) -> InstallationCandidate:
    return await asyncio.to_thread(_probe_selected_version, candidate,
                                   "codex_app_server", cwd=cwd, env=env)


def _probe_selected_version(candidate: InstallationCandidate, adapter_id: str, *,
                            cwd: str | Path,
                            env: Mapping[str, str]) -> InstallationCandidate:
    """Bounded read-only version observation; never grants a capability."""
    # C2/R07: an active probe spawns a version process; the containment
    # gate must refuse BEFORE any observer runs in an environment whose
    # backend cannot honor the owned-tree contract.
    require_containment()
    if candidate.adapter_id != adapter_id or candidate.trust != "selected":
        raise CoreError("BINDING_NOT_AUTHORIZED", "version_probe")
    root = Path(cwd)
    if not root.is_absolute() or not root.is_dir():
        raise CoreError("WORKSPACE_UNAVAILABLE", "version_probe")
    executable = Path(candidate.executable)
    if (selected_fingerprint(candidate) != candidate.fingerprint or
            binary_architecture(executable) != candidate.architecture):
        raise CoreError("PROFILE_DRIFT", "version_probe")
    from .native.adapters import compatibility
    observer = {
        "claude_stream": compatibility.claude_version_observation,
        "pi_rpc": compatibility.pi_version_observation,
        "codex_app_server": compatibility.codex_version_observation,
    }[adapter_id]
    command = ((str(executable), candidate.launch_script, "--version")
               if candidate.launch_script is not None else
               (str(executable), "--version"))
    report = observer(command, cwd=str(root),
                      env={key: value for key, value in env.items()
                           if key.upper() in _PROBE_ENV})
    if selected_fingerprint(candidate) != candidate.fingerprint:
        raise CoreError("PROFILE_DRIFT", "version_probe")
    return replace(candidate, version=report["native_version"])


def discover_pi_releases(install_root: str | Path, node_path: str | Path,
                         *, trusted_roots: tuple[Path, ...] = ()) \
        -> tuple[InstallationCandidate, ...]:
    """Discover Pi Node+CLI pairs from a releases directory (PC10).

    Passive: enumerates ``releases/*/node_modules/@earendil-works/
    pi-coding-agent/dist/bundle/cli.js`` under ``install_root`` and pairs
    each with the explicitly supplied Node executable. Nothing is
    executed, no wrapper is interpreted, and candidates outside
    ``trusted_roots`` (when supplied) are not auto-trusted - the host
    approves the binding. Ordered newest-first by directory name.
    """
    root = Path(install_root)
    if not root.is_absolute():
        raise CoreError("BINARY_NOT_FOUND", "discovery")
    releases = root / "releases"
    if not releases.is_dir():
        return ()
    cli_suffix = Path("node_modules") / "@earendil-works" / \
        "pi-coding-agent" / "dist" / "bundle" / "cli.js"
    candidates = []
    for release in sorted(releases.iterdir(), reverse=True):
        if not release.is_dir():
            continue
        cli = release / cli_suffix
        try:
            selected = candidate_pi_node_cli(node_path, cli,
                                             trusted_roots=trusted_roots)
        except (CoreError, OSError):
            continue
        candidates.append(selected)
    return tuple(candidates)


_SHIM_TARGET = re.compile(
    r'"([^"]+)"\s+%\*\s*\Z')
_SHIM_NODE = re.compile(
    r'SET\s+"_prog=(node(?:\.exe)?)"', re.IGNORECASE)


def resolve_windows_npm_shim(shim_path: str | Path) -> Path:
    """Resolve a known npm ``.cmd`` shim to its target script, passively.

    Parses only the two documented npm-cmd-shim shapes (node.exe beside
    the shim, or ``node`` from PATH, launching one quoted ``.js`` target
    with `` %*``). Any other content - extra commands, URLs, dynamic
    expansion - is refused with ``NATIVE_VERSION_UNQUALIFIED``: the
    wrapper is never executed during discovery (RC-10-03).
    """
    if os.name != "nt":
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
    path = Path(shim_path)
    if path.suffix.lower() != ".cmd" or not path.is_file():
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery") from exc
    if len(text) > 8192:
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
    target = None
    for line in text.splitlines():
        match = _SHIM_TARGET.search(line)
        if match:
            candidate_target = match.group(1)
            if not candidate_target.lower().endswith(".js"):
                raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
            if "%" in candidate_target:
                raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
            target = candidate_target
    if target is None:
        raise CoreError("NATIVE_VERSION_UNQUALIFIED", "discovery")
    resolved = Path(target)
    if not resolved.is_absolute():
        resolved = (path.parent / resolved).resolve(strict=True)
    if not resolved.is_file():
        raise CoreError("BINARY_NOT_FOUND", "discovery")
    return resolved


def discover_path(adapter_id: str, *, path_env: str | None = None,
                  trusted_roots: tuple[Path, ...] = ()) -> tuple[InstallationCandidate, ...]:
    """Return only candidates under trusted roots; never search current cwd."""
    name = EXECUTABLE_NAMES.get(adapter_id)
    if name is None:
        raise CoreError("CAPABILITY_UNSUPPORTED", "discovery")
    suffixes = (".exe", ".com") if os.name == "nt" else ("",)
    cwd = Path.cwd().resolve()
    found: dict[str, InstallationCandidate] = {}
    for entry in (path_env if path_env is not None else os.environ.get("PATH", "")).split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry)
        if not directory.is_absolute():
            continue
        try:
            directory = directory.resolve(strict=True)
        except OSError:
            continue
        if directory == cwd:
            continue
        for suffix in suffixes:
            path = directory / (name + suffix)
            if not path.is_file():
                continue
            try:
                item = candidate(adapter_id, path, trusted_roots=trusted_roots)
            except (CoreError, OSError):
                continue
            # C11/A11-01 + alias policy: key by the installation ref -
            # PATH duplicates/symlinks to the SAME canonical target are
            # ONE installation; distinct targets stay distinct rows.
            found[item.installation_ref
                  or installation_ref(adapter_id, item.executable)] = item
    return tuple(found.values())
