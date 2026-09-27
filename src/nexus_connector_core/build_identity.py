"""Portable build identity versus local binding fingerprint (C1/PC09).

``build_identity`` qualifies *content*: a path-free digest of the
executable artifacts a launcher actually loads. Two equivalent
installations in different directories produce the same build identity,
so qualification of a build travels with its bytes.

``binding_fingerprint`` (discovery) stays path-bound on purpose: moving
an installation or swapping a file must invalidate the approved local
binding (the audit's standing observation). Nothing here weakens that.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .protocol import canonical_json

__all__ = ["executable_build_identity", "pi_build_identity",
           "BUILD_IDENTITY_ALGORITHM"]

BUILD_IDENTITY_ALGORITHM = "core.build_identity.v2"
# C3/S06: bounded coverage headroom. The real 0.2.x-qualified Pi
# release closure measures 14,094 files / 101.3 MiB / 118 packages;
# the cap stays strict and refusal of larger layouts is explicit.
_MAX_MANIFEST_ENTRIES = 32768
_MAX_MANIFEST_BYTES = 256 * 1024 * 1024


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def executable_build_identity(executable: str | os.PathLike) -> str:
    """Portable identity of a single-file executable: content only."""
    path = Path(executable)
    if not path.is_absolute():
        raise ValueError("build identity requires an absolute path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("build identity requires a regular file")
    identity = {
        "algorithm": BUILD_IDENTITY_ALGORITHM,
        "kind": "executable",
        "sha256": _file_digest(resolved).split(":", 1)[1],
        "size": resolved.stat().st_size,
    }
    return "sha256:" + hashlib.sha256(
        canonical_json(identity)).hexdigest()


def pi_build_identity(node: str | os.PathLike,
                      package_root: str | os.PathLike) -> str:
    """Portable identity of the Node + Pi-package launch pair.

    ``package_root`` is the ``@earendil-works/pi-coding-agent`` package
    directory (C2/R06: never the ``@earendil-works`` scope directory, so
    unrelated sibling packages cannot perturb the identity). The manifest
    enumerates the package tree with *relative* paths and content digests
    only — no absolute paths, no user data.

    C2/R06 + C3/S06: the loadable set also covers the package's DECLARED
    production dependencies (``dependencies`` in package.json), resolved
    through the standard node_modules lookup — including packages hoisted
    OUTSIDE the scope directory — transitively, under strict limits. Each
    dependency contributes its FULL content manifest (every file of the
    package), which is the only bounded way to cover every loading form
    Node supports: implicit ``index.js`` resolution, relative imports from
    any entry, and ``exports`` maps alike. ``main``/``bin`` alone proved
    insufficient (S06); a digest that cannot represent the layout refuses
    (ValueError) rather than qualifying it silently. Undeclared packages
    never enter the identity. Semantic changes to this coverage version
    the algorithm tag (v2) and require deliberate requalification of the
    allowlist.
    """
    node_path = Path(node)
    root = Path(package_root)
    if not node_path.is_absolute() or not root.is_absolute():
        raise ValueError("build identity requires absolute inputs")
    node_resolved = node_path.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    if not node_resolved.is_file() or not root_resolved.is_dir():
        raise ValueError("invalid pi build identity inputs")
    entries = []

    def _add_tree(directory: Path, prefix: str) -> None:
        nonlocal total
        for current in sorted(directory.rglob("*")):
            if not current.is_file():
                continue
            total = _add_entry(entries, total, current,
                               prefix + current.relative_to(directory)
                               .as_posix())

    total = 0

    _add_tree(root_resolved, "")

    # The installation root bounds the node_modules lookup: the directory
    # that CONTAINS the top-level node_modules the package lives under.
    install_root = _node_install_root(root_resolved)
    queue = [root_resolved]
    seen = {root_resolved.resolve()}
    packages = 0
    while queue:
        package_dir = queue.pop(0)
        packages += 1
        if packages > _MAX_DEPENDENCY_PACKAGES:
            raise ValueError("pi dependency closure exceeds bounded size")
        for name in _declared_dependencies(package_dir):
            resolved = _resolve_node_modules_package(package_dir, name,
                                                     install_root)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            _add_tree(resolved, f"deps/{name}/")
            queue.append(resolved)

    identity = {
        "algorithm": BUILD_IDENTITY_ALGORITHM,
        "kind": "pi_node_package",
        "node_sha256": _file_digest(node_resolved).split(":", 1)[1],
        "node_size": node_resolved.stat().st_size,
        "package": entries,
    }
    return "sha256:" + hashlib.sha256(
        canonical_json(identity)).hexdigest()


_MAX_DEPENDENCY_PACKAGES = 512


def _add_entry(entries: list, total: int, path: Path, relative: str) -> int:
    """Append one bounded manifest entry (path-free relative + digest)."""
    if (len(entries) >= _MAX_MANIFEST_ENTRIES or
            total >= _MAX_MANIFEST_BYTES):
        raise ValueError("pi package manifest exceeds bounded size")
    size = path.stat().st_size
    entries.append({"path": relative,
                    "sha256": _file_digest(path).split(":", 1)[1],
                    "size": size})
    return total + size


def _node_install_root(package_root: Path) -> Path:
    """The directory containing the top-level node_modules of a package."""
    parent = package_root.parent
    if parent.name == "node_modules":
        return parent.parent
    grandparent = parent.parent
    if grandparent.name == "node_modules":
        return grandparent.parent
    return parent


def _declared_dependencies(package_dir: Path) -> tuple[str, ...]:
    manifest = package_dir / "package.json"
    if not manifest.is_file():
        return ()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"unreadable package.json in {package_dir.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid package.json in {package_dir.name}")
    dependencies = data.get("dependencies")
    if dependencies is None:
        return ()
    if not isinstance(dependencies, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in dependencies.items()):
        raise ValueError(f"invalid dependencies in {package_dir.name}")
    return tuple(sorted(dependencies))


def _resolve_node_modules_package(package_dir: Path, name: str,
                                  install_root: Path) -> Path | None:
    """Standard node resolution, bounded by the installation root."""
    if not name or name.startswith(("/", "\\")) or "\\" in name:
        return None
    current = package_dir
    while True:
        candidate = current / "node_modules" / Path(*name.split("/"))
        if candidate.is_dir():
            return candidate.resolve(strict=True)
        if current == install_root or current.parent == current:
            break
        current = current.parent
    return None
