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
import stat
from pathlib import Path

from .discovery_control import check_discovery_cancelled
from .protocol import canonical_json

__all__ = ["executable_build_identity", "pi_build_identity",
           "BUILD_IDENTITY_ALGORITHM"]

#: C4/T06: coverage v3 - declared relations now include INSTALLED
#: optionalDependencies and peerDependencies (absence is recorded, so
#: installing one later changes the identity), and the closure preserves
#: topology via importer-relative logical paths (two importers resolving
#: different versions of one name never collide). Requalification of the
#: allowlist is required for every semantic change.
BUILD_IDENTITY_ALGORITHM = "core.build_identity.v3"
# C3/S06 + C4/T06: bounded coverage headroom. The real 0.2.x-qualified Pi
# release closure measures 14,094 files / 101.3 MiB / 118 packages; the
# caps stay strict and refusal of larger layouts is explicit.
_MAX_MANIFEST_ENTRIES = 32768
_MAX_MANIFEST_BYTES = 256 * 1024 * 1024
_MAX_DEPENDENCY_PACKAGES = 512
# C4/T07: enumeration itself is bounded - directories visited, depth and
# files collected are capped so a hostile layout cannot materialize an
# unbounded path list before the budget check fires.
_MAX_DIRECTORIES = 65536
_MAX_DEPTH = 48
_READ_CHUNK = 1024 * 1024


def _file_digest(path: Path) -> str:
    check_discovery_cancelled()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_READ_CHUNK), b""):
            check_discovery_cancelled()
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _file_digest_counted(path: Path, expected: int) -> str:
    """Digest while counting the bytes ACTUALLY read (C4/T07): a file
    growing between stat and read refuses instead of silently exceeding
    the budget."""
    check_discovery_cancelled()
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        # Small package files must not allocate a megabyte for every read.
        # One extra byte still detects growth, including after the exact
        # expected size has been consumed. No content or EOF check is skipped.
        while chunk := stream.read(min(_READ_CHUNK, expected - read + 1)):
            check_discovery_cancelled()
            read += len(chunk)
            if read > expected:
                raise ValueError(
                    f"file grew during read: {path.name}")
            digest.update(chunk)
    if read != expected:
        raise ValueError(f"file changed size during read: {path.name}")
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


def _iter_tree_files(directory: Path):
    """Bounded, INCREMENTAL enumeration (C4/T07 + C5/U07): os.scandir
    consumed entry-by-entry with a per-NAME budget - a wide directory
    never materializes a full name list before the cap refuses. Regular
    files only; in-scope symlinks followed by content, anything escaping
    the walked root refuses. The iterator is closed on every path.
    """
    dirs_visited = 0
    names_seen = 0
    collected = []

    def walk(current: Path, depth: int) -> None:
        nonlocal dirs_visited, names_seen
        check_discovery_cancelled()
        if depth > _MAX_DEPTH:
            raise ValueError("pi package tree exceeds bounded depth")
        dirs_visited += 1
        if dirs_visited > _MAX_DIRECTORIES:
            raise ValueError("pi package tree exceeds bounded directories")
        names = []
        try:
            iterator = os.scandir(current)
        except OSError as exc:
            raise ValueError("unreadable directory in package") from exc
        try:
            for entry in iterator:
                check_discovery_cancelled()
                names_seen += 1
                if names_seen > _MAX_MANIFEST_ENTRIES:
                    # C6/M01: refuse AT the first name beyond the budget
                    # (cap+1 obtained in total, counting the sentinel that
                    # proves the excess) - never cap+2, never after
                    # materializing the directory.
                    raise ValueError(
                        "pi package manifest exceeds bounded size")
                names.append(entry.name)
        except OSError as exc:
            raise ValueError("unreadable entry in package") from exc
        finally:
            iterator.close()
        for name in sorted(names):
            check_discovery_cancelled()
            if len(collected) > _MAX_MANIFEST_ENTRIES:
                raise ValueError("pi package manifest exceeds bounded size")
            path = current / name
            try:
                st = os.lstat(path)
            except OSError as exc:
                raise ValueError("unreadable entry in package") from exc
            if stat.S_ISLNK(st.st_mode):
                # Layout policy (C4/T06): links INSIDE the walked root
                # are covered by content; a link escaping it refuses -
                # the identity never reads outside the authorized scope.
                try:
                    target = path.resolve(strict=True)
                except OSError as exc:
                    raise ValueError(
                        f"broken link in package: {name}") from exc
                if not target.is_relative_to(directory.resolve()):
                    raise ValueError(
                        f"link escapes the package scope: {name}")
                st = target.stat()
            if stat.S_ISDIR(st.st_mode):
                walk(path, depth + 1)
            elif stat.S_ISREG(st.st_mode):
                collected.append(path)
            else:
                # FIFOs, devices, sockets: refused BEFORE any blocking
                # read (C4/T07).
                raise ValueError(
                    f"unsupported special file in package: {name}")

    walk(directory, 0)
    return collected


def pi_build_identity(node: str | os.PathLike,
                      package_root: str | os.PathLike) -> str:
    """Portable identity of the Node + Pi-package launch pair.

    ``package_root`` is the ``@earendil-works/pi-coding-agent`` package
    directory (C2/R06: never the ``@earendil-works`` scope directory, so
    unrelated sibling packages cannot perturb the identity). The manifest
    enumerates the package tree with *relative* paths and content digests
    only - no absolute paths, no user data.

    C2/R06 + C3/S06 + C4/T06: the loadable set covers the package's
    DECLARED production relations - ``dependencies`` plus INSTALLED
    ``optionalDependencies``/``peerDependencies`` - resolved through the
    standard node_modules lookup, transitively, under strict limits. The
    ABSENCE of an optional/peer relation is recorded, so installing one
    later changes the identity. Each reached package contributes its
    FULL content manifest under an importer-relative logical path (two
    importers resolving different versions of one name never collide).
    A digest that cannot represent the layout refuses (ValueError)
    rather than qualifying it silently; undeclared packages never enter
    the identity. C4/T07: budgets are enforced BEFORE reading (projected
    totals), enumeration is bounded, and growth during read refuses.
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

    def _add_tree(directory: Path, prefix: str) -> None:
        nonlocal total
        for current in _iter_tree_files(directory):
            check_discovery_cancelled()
            relative = prefix + current.relative_to(directory).as_posix()
            total = _add_entry(entries, total, current, relative)

    _add_tree(root_resolved, "")

    install_root = _node_install_root(root_resolved)
    # C4/T06: importer-relative logical topology ("@/name/subname").
    queue = [(root_resolved, "@")]
    seen = {root_resolved.resolve()}
    absent_relations: list[str] = []
    packages = 0
    while queue:
        check_discovery_cancelled()
        package_dir, logical = queue.pop(0)
        packages += 1
        if packages > _MAX_DEPENDENCY_PACKAGES:
            raise ValueError("pi dependency closure exceeds bounded size")
        for name, required in _declared_relations(package_dir):
            resolved = _resolve_node_modules_package(package_dir, name,
                                                     install_root)
            if resolved is None:
                if not required:
                    # Recorded absence: installing it later must change
                    # the identity (C4/T06).
                    absent_relations.append(f"{logical}:{name}")
                else:
                    raise ValueError(
                        f"declared dependency missing from installation: "
                        f"{name}")
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            dep_logical = f"{logical}/{name}"
            _add_tree(resolved, f"{dep_logical}/")
            queue.append((resolved, dep_logical))

    identity = {
        "algorithm": BUILD_IDENTITY_ALGORITHM,
        "kind": "pi_node_package",
        "node_sha256": _file_digest(node_resolved).split(":", 1)[1],
        "node_size": node_resolved.stat().st_size,
        "package": entries,
        "relations_absent": sorted(absent_relations),
    }
    return "sha256:" + hashlib.sha256(
        canonical_json(identity)).hexdigest()


def _add_entry(entries: list, total: int, path: Path, relative: str) -> int:
    """Append one bounded manifest entry (path-free relative + digest).

    C4/T07: the PROJECTED total is validated BEFORE the file is read;
    hitting the limit exactly is allowed, exceeding it by one byte
    refuses before any digest work.
    """
    if len(entries) >= _MAX_MANIFEST_ENTRIES:
        raise ValueError("pi package manifest exceeds bounded size")
    try:
        st = path.stat()
        size = st.st_size
    except OSError as exc:
        raise ValueError("unreadable file in package") from exc
    if total + size > _MAX_MANIFEST_BYTES:
        raise ValueError("pi package manifest exceeds bounded size")
    entries.append({"path": relative,
                    "sha256": _file_digest_counted(path, size)
                    .split(":", 1)[1],
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


def _validated_relation_map(package_dir: Path, key: str) -> dict:
    manifest = package_dir / "package.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"unreadable package.json in {package_dir.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid package.json in {package_dir.name}")
    relations = data.get(key)
    if relations is None:
        return {}
    if not isinstance(relations, dict):
        raise ValueError(f"invalid {key} in {package_dir.name}")
    if key == "peerDependenciesMeta":
        # Values are objects ("optional": true), validated structurally.
        if not all(isinstance(name, str) and isinstance(value, dict)
                   for name, value in relations.items()):
            raise ValueError(
                f"invalid {key} in {package_dir.name}")
        return relations
    if not all(isinstance(name, str) and isinstance(value, str)
               for name, value in relations.items()):
        raise ValueError(f"invalid {key} in {package_dir.name}")
    return relations


def _declared_relations(package_dir: Path) -> tuple[tuple[str, bool], ...]:
    """(name, required) for dependencies + optional/peer relations.

    ``dependencies`` are required (a missing one refuses the layout);
    optional/peer relations may be absent - the absence is recorded so a
    later install changes the identity (C4/T06).
    """
    combined: dict[str, bool] = {}
    for name in _validated_relation_map(package_dir, "dependencies"):
        combined[name] = True
    for key in ("optionalDependencies", "peerDependencies"):
        for name in _validated_relation_map(package_dir, key):
            combined.setdefault(name, False)
    # peerDependenciesMeta.optional marks peers that MAY be absent; a peer
    # not so marked stays required. Its values are OBJECTS, not strings.
    meta = _validated_relation_map(package_dir, "peerDependenciesMeta")
    for name, value in meta.items():
        if isinstance(value, dict) and value.get("optional") is True:
            if name in combined:
                combined[name] = False
    return tuple(sorted(combined.items(), key=lambda item: item[0]))


def _resolve_node_modules_package(package_dir: Path, name: str,
                                  install_root: Path) -> Path | None:
    """Standard node resolution, bounded by the installation root."""
    if not name or name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/"):
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

def launch_artifact_signature(node: str | os.PathLike,
                              cli: str | os.PathLike) -> tuple:
    """Lightweight launch seal for the Pi Node+CLI pair (C5/U05).

    Stat-only aggregate over the REAL artifact set the qualified build
    covers: the Node binary, the CLI entrypoint and every file of the
    declared dependency closure (same walker/caps as the identity, no
    hashing). Used at the launch frontiers to detect ordinary drift of
    the CLI or any dependency after prepare - argv[0] alone is Node and
    proves nothing about the rest. Residual window: a rewrite that
    preserves every (size, mtime_ns) is not representable without
    re-hashing; declared, not claimed atomic.
    """
    node_path = Path(node).resolve(strict=True)
    cli_path = Path(cli).resolve(strict=True)
    package_root = cli_path.parents[2]
    install_root = _node_install_root(package_root)
    count = 0
    total = 0
    newest = 0
    for path in _iter_tree_files(package_root):
        try:
            st = path.stat()
        except OSError as exc:
            raise ValueError("unreadable file in launch seal") from exc
        count += 1
        total += st.st_size
        newest = max(newest, st.st_mtime_ns)
    queue = [(package_root, "@")]
    seen = {package_root.resolve()}
    while queue:
        package_dir, _logical = queue.pop(0)
        for name, _required in _declared_relations(package_dir):
            resolved = _resolve_node_modules_package(package_dir, name,
                                                     install_root)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            for path in _iter_tree_files(resolved):
                try:
                    st = path.stat()
                except OSError as exc:
                    raise ValueError(
                        "unreadable file in launch seal") from exc
                count += 1
                total += st.st_size
                newest = max(newest, st.st_mtime_ns)
            queue.append((resolved, _logical))
    def _stat_tuple(path: Path):
        try:
            st = path.stat()
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None
    return (_stat_tuple(node_path), _stat_tuple(cli_path),
            count, total, newest)
