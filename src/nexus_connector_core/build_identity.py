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
import os
from pathlib import Path

from .protocol import canonical_json

__all__ = ["executable_build_identity", "pi_build_identity",
           "BUILD_IDENTITY_ALGORITHM"]

BUILD_IDENTITY_ALGORITHM = "core.build_identity.v1"
_MAX_MANIFEST_ENTRIES = 4096
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

    ``package_root`` is the ``@earendil-works/pi-coding-agent`` directory
    (or the release directory containing it); the manifest enumerates the
    package tree with *relative* paths and content digests only — no
    absolute paths, no user data. Later loads beyond the manifest would
    change the package contents and therefore the identity.
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
    total = 0
    for current in sorted(root_resolved.rglob("*")):
        if not current.is_file():
            continue
        if len(entries) >= _MAX_MANIFEST_ENTRIES or total >= _MAX_MANIFEST_BYTES:
            raise ValueError("pi package manifest exceeds bounded size")
        relative = current.relative_to(root_resolved).as_posix()
        size = current.stat().st_size
        entries.append({"path": relative,
                        "sha256": _file_digest(current).split(":", 1)[1],
                        "size": size})
        total += size
    identity = {
        "algorithm": BUILD_IDENTITY_ALGORITHM,
        "kind": "pi_node_package",
        "node_sha256": _file_digest(node_resolved).split(":", 1)[1],
        "node_size": node_resolved.stat().st_size,
        "package": entries,
    }
    return "sha256:" + hashlib.sha256(
        canonical_json(identity)).hexdigest()
