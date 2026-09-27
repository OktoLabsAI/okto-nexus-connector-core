"""PC09: portable build identity versus path-bound binding fingerprint."""

import shutil
import sys
from pathlib import Path

import pytest

from nexus_connector_core.build_identity import (
    executable_build_identity, pi_build_identity,
)
from nexus_connector_core.discovery import candidate, candidate_pi_node_cli
from nexus_connector_core.native.adapters import compatibility


def _make_executable(root: Path, name: str, content: bytes = b"binary-x") -> Path:
    path = root / name
    path.write_bytes(content)
    if sys.platform != "win32":
        path.chmod(0o755)
    return path


def _make_pi_tree(root: Path, node_content: bytes = b"node-bytes",
                  cli_content: bytes = b"// cli") -> Path:
    package = root / "releases" / "0.87.1" / "node_modules" / \
        "@earendil-works" / "pi-coding-agent"
    bundle = package / "dist" / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "cli.js").write_bytes(cli_content)
    (package / "package.json").write_bytes(b'{"name":"@earendil-works/pi-coding-agent"}')
    _make_executable(root, "node.exe" if sys.platform == "win32" else "node",
                     node_content)
    return root


def test_rc_09_01_same_build_different_paths(tmp_path):
    first_root = tmp_path / "install-a"
    second_root = tmp_path / "install-b"
    for root in (first_root, second_root):
        _make_pi_tree(root)
    node_name = "node.exe" if sys.platform == "win32" else "node"

    def candidate_for(root):
        return candidate_pi_node_cli(
            str(root / node_name),
            str(root / "releases" / "0.87.1" / "node_modules" /
                "@earendil-works" / "pi-coding-agent" / "dist" / "bundle" /
                "cli.js"),
            explicit=True)

    first = candidate_for(first_root)
    second = candidate_for(second_root)
    # Portable identity: identical content -> identical build identity.
    assert first.build_identity == second.build_identity
    # Local binding: different paths -> different fingerprints (the audit's
    # standing observation must remain true).
    assert first.fingerprint != second.fingerprint


def test_rc_09_02_material_change_alters_identity(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _make_pi_tree(root_a, cli_content=b"// cli v1")
    _make_pi_tree(root_b, cli_content=b"// cli v2")
    node_name = "node.exe" if sys.platform == "win32" else "node"
    identity_a = pi_build_identity(root_a / node_name,
                                   root_a / "releases" / "0.87.1" /
                                   "node_modules" / "@earendil-works" /
                                   "pi-coding-agent")
    identity_b = pi_build_identity(root_b / node_name,
                                   root_b / "releases" / "0.87.1" /
                                   "node_modules" / "@earendil-works" /
                                   "pi-coding-agent")
    assert identity_a != identity_b


def test_rc_09_03_faked_version_string_never_merges_builds(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    binary_a = _make_executable(tmp_path / "x", "codex.exe", b"real-bytes")
    binary_b = _make_executable(tmp_path / "y", "codex.exe", b"impostor-bytes")
    assert (executable_build_identity(binary_a) !=
            executable_build_identity(binary_b))


def test_qualification_via_portable_identity(tmp_path):
    # Simulated already-qualified build whose bytes live in a new path.
    binary = _make_executable(tmp_path, "codex.exe", b"qualified-bytes")
    identity = executable_build_identity(binary)
    key = ("codex", "9.9.9", sys.platform, "x86_64", identity)
    compatibility.QUALIFIED_BUILD_IDENTITIES.add(key)
    try:
        assert compatibility.qualified_build(
            "codex", "9.9.9", sys.platform, "x86_64",
            "sha256:" + "0" * 64, build_identity=identity)
        # Without the identity, the unrelated fingerprint stays refused.
        assert not compatibility.qualified_build(
            "codex", "9.9.9", sys.platform, "x86_64", "sha256:" + "0" * 64)
    finally:
        compatibility.QUALIFIED_BUILD_IDENTITIES.discard(key)


def test_production_identity_grants_recorded_from_campaigns():
    # The three authorized campaign builds carry portable identity grants.
    assert compatibility.qualified_build(
        "codex", "0.157.0", "win32", "x86_64", "sha256:" + "0" * 64,
        build_identity="sha256:df63d86e72bc1a27f13899ad0467c4b312d8ee2cb67ae3a09e37f734d9f0edcb")
    assert compatibility.qualified_build(
        "pi", "0.87.1", "win32", "x86_64", "sha256:" + "0" * 64,
        build_identity="sha256:bc3b22f8927a334f75d4a5d824e7a280c105b4929910cd127b1d0173e4284914")
    # C2/R06 + C3/S06: pre-v2 (partial) identities no longer grant.
    assert not compatibility.qualified_build(
        "pi", "0.87.1", "win32", "x86_64", "sha256:" + "0" * 64,
        build_identity="sha256:b454b39171e7428e721ecc01be6654c3608a9091d398c3d3d445897a91a67e43")
    assert not compatibility.qualified_build(
        "pi", "0.87.1", "win32", "x86_64", "sha256:" + "0" * 64,
        build_identity="sha256:d4f09928e4a7043d1d6bd742a4ead3344d3b18b3990410b797ba65169a0cf583")
    assert compatibility.qualified_build(
        "claude_code", "2.1.282", "win32", "x86_64", "sha256:" + "0" * 64,
        build_identity="sha256:b9c8e2e61cc523f4d78630d6141e843c41fbe530cd297e7d4af8acd44841bed9")


def test_rc_09_04_drift_blocks_prepare_via_identity(tmp_path):
    binary = _make_executable(tmp_path, "codex.exe", b"original")
    selected = candidate("codex_app_server", binary, explicit=True)
    from nexus_connector_core.models import LaunchIntent
    from nexus_connector_core.profiles import prepare_launch
    launch = prepare_launch(LaunchIntent("ag", "ws", "codex_app_server"),
                            selected, tmp_path)
    # Material content change: the portable identity no longer matches even
    # if the path-bound fingerprint were somehow re-pinned.
    binary.write_bytes(b"tampered")
    from nexus_connector_core import CoreError
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        prepare_launch(LaunchIntent("ag", "ws", "codex_app_server"),
                       selected, tmp_path)
