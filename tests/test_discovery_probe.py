import asyncio
import os
import struct
import sys

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.discovery import (binary_architecture, candidate,
                                            candidate_pi_node_cli,
                                            probe_selected_claude, probe_selected_codex,
                                            probe_selected_pi)
from nexus_connector_core.native.adapters import compatibility


def pe(machine: int) -> bytes:
    data = bytearray(134)
    data[:2] = b"MZ"
    data[60:64] = struct.pack("<I", 128)
    data[128:134] = b"PE\x00\x00" + struct.pack("<H", machine)
    return bytes(data)


def test_bounded_binary_architecture_headers(tmp_path):
    binary = tmp_path / "native.exe"
    binary.write_bytes(pe(0x8664))
    assert binary_architecture(binary) == "x86_64"
    binary.write_bytes(pe(0xAA64))
    assert binary_architecture(binary) == "aarch64"
    elf = bytearray(64)
    elf[:4], elf[5], elf[18:20] = b"\x7fELF", 1, struct.pack("<H", 62)
    binary.write_bytes(elf)
    assert binary_architecture(binary) == "x86_64"
    binary.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C))
    assert binary_architecture(binary) == "aarch64"
    oversized = bytearray(64)
    oversized[:2], oversized[60:64] = b"MZ", struct.pack("<I", 0xFFFFFFFF)
    binary.write_bytes(oversized)
    assert binary_architecture(binary) is None


def test_candidate_carries_architecture_without_executing(tmp_path):
    binary = tmp_path / ("claude.exe" if os.name == "nt" else "claude")
    binary.write_bytes(pe(0x8664))
    if os.name != "nt":
        binary.chmod(0o755)
    selected = candidate("claude_stream", binary, explicit=True)
    assert selected.architecture == "x86_64"
    assert selected.version is None


def test_selected_version_probe_is_observation_only(tmp_path, monkeypatch):
    binary = tmp_path / ("claude.exe" if os.name == "nt" else "claude")
    binary.write_bytes(pe(0x8664))
    if os.name != "nt":
        binary.chmod(0o755)
    selected = candidate("claude_stream", binary, explicit=True)
    calls = []

    def observe(command, *, cwd, env):
        calls.append((command, cwd, env))
        return {"native_version": "2.1.282", "capabilities_verified": False}

    monkeypatch.setattr(compatibility, "claude_version_observation", observe)

    async def run():
        probed = await probe_selected_claude(selected, cwd=tmp_path,
                                             env={"PATH": "sealed", "ANTHROPIC_API_KEY": "secret"})
        assert probed.version == "2.1.282"
        assert probed.architecture == "x86_64"
        assert selected.version is None
        assert calls == [((str(binary), "--version"), str(tmp_path), {"PATH": "sealed"})]
        binary.write_bytes(pe(0xAA64))
        with pytest.raises(CoreError, match="PROFILE_DRIFT"):
            await probe_selected_claude(selected, cwd=tmp_path, env={})

    asyncio.run(run())


def test_selected_pi_probe_seals_environment_and_detects_drift(tmp_path, monkeypatch):
    binary = tmp_path / ("pi.exe" if os.name == "nt" else "pi")
    binary.write_bytes(pe(0x8664))
    if os.name != "nt":
        binary.chmod(0o755)
    selected = candidate("pi_rpc", binary, explicit=True)
    calls = []

    def observe(command, *, cwd, env):
        calls.append((command, cwd, env))
        return {"native_version": "0.85.1", "capabilities_verified": False}

    monkeypatch.setattr(compatibility, "pi_version_observation", observe)

    async def run():
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await probe_selected_pi(candidate("claude_stream", binary, explicit=True),
                                    cwd=tmp_path, env={})
        probed = await probe_selected_pi(selected, cwd=tmp_path,
                                         env={"PATH": "sealed", "PI_API_KEY": "secret"})
        assert probed.version == "0.85.1"
        assert selected.version is None
        assert calls == [((str(binary), "--version"), str(tmp_path), {"PATH": "sealed"})]
        binary.write_bytes(pe(0xAA64))
        with pytest.raises(CoreError, match="PROFILE_DRIFT"):
            await probe_selected_pi(selected, cwd=tmp_path, env={})

    asyncio.run(run())


def test_pi_node_cli_probe_seals_both_selected_files(tmp_path, monkeypatch):
    node = tmp_path / ("node.exe" if os.name == "nt" else "node")
    node.write_bytes(pe(0x8664))
    if os.name != "nt":
        node.chmod(0o755)
    script = (tmp_path / "node_modules" / "@earendil-works" /
              "pi-coding-agent" / "dist" / "bundle" / "cli.js")
    script.parent.mkdir(parents=True)
    script.write_text("// pi cli\n", encoding="utf-8")
    selected = candidate_pi_node_cli(node, script, explicit=True)
    calls = []

    def observe(command, *, cwd, env):
        calls.append((command, cwd, env))
        return {"native_version": "0.87.1", "capabilities_verified": False}

    monkeypatch.setattr(compatibility, "pi_version_observation", observe)

    async def run():
        probed = await probe_selected_pi(selected, cwd=tmp_path,
                                         env={"PATH": "sealed", "PI_API_KEY": "secret"})
        assert probed.version == "0.87.1"
        assert calls == [((str(node), str(script), "--version"),
                          str(tmp_path), {"PATH": "sealed"})]
        script.write_text("// changed\n", encoding="utf-8")
        with pytest.raises(CoreError, match="PROFILE_DRIFT"):
            await probe_selected_pi(selected, cwd=tmp_path, env={})

    asyncio.run(run())


def test_selected_codex_probe_seals_environment_and_detects_drift(tmp_path, monkeypatch):
    binary = tmp_path / ("codex.exe" if os.name == "nt" else "codex")
    binary.write_bytes(pe(0x8664))
    if os.name != "nt":
        binary.chmod(0o755)
    selected = candidate("codex_app_server", binary, explicit=True)
    calls = []

    def observe(command, *, cwd, env):
        calls.append((command, cwd, env))
        return {"native_version": "0.157.0", "capabilities_verified": False}

    monkeypatch.setattr(compatibility, "codex_version_observation", observe)

    async def run():
        probed = await probe_selected_codex(
            selected, cwd=tmp_path,
            env={"PATH": "sealed", "OPENAI_API_KEY": "secret"})
        assert probed.version == "0.157.0"
        assert selected.version is None
        assert calls == [((str(binary), "--version"), str(tmp_path), {"PATH": "sealed"})]
        binary.write_bytes(pe(0xAA64))
        with pytest.raises(CoreError, match="PROFILE_DRIFT"):
            await probe_selected_codex(selected, cwd=tmp_path, env={})

    asyncio.run(run())


def test_codex_version_observation_accepts_only_narrow_cli_output(monkeypatch):
    monkeypatch.setattr(compatibility, "_version_output",
                        lambda *args, **kwargs: b"codex-cli 0.157.0\n")
    valid = compatibility.codex_version_observation(("codex", "--version"),
                                                    cwd="/", env={})
    assert valid["native_version"] == "0.157.0"
    assert not valid["capabilities_verified"]
    monkeypatch.setattr(compatibility, "_version_output",
                        lambda *args, **kwargs: b"codex-cli 0.157.0 extra\n")
    invalid = compatibility.codex_version_observation(("codex", "--version"),
                                                      cwd="/", env={})
    assert invalid["native_version"] is None


@pytest.mark.skipif(os.name != "nt", reason="Windows wrapper policy")
def test_codex_command_wrapper_is_not_a_native_candidate(tmp_path):
    wrapper = tmp_path / "codex.cmd"
    wrapper.write_text("@echo off\n")
    with pytest.raises(CoreError, match="NATIVE_VERSION_UNQUALIFIED"):
        candidate("codex_app_server", wrapper, explicit=True)


def test_qualification_requires_exact_platform_architecture_and_binary(monkeypatch):
    qualified = set()
    monkeypatch.setattr(compatibility, "QUALIFIED_BUILDS", qualified)
    key = ("claude_code", "2.1.282", sys.platform, "x86_64", "sha256:abc")
    assert not compatibility.qualified_build(*key)
    qualified.add(key)
    assert compatibility.qualified_build(*key)
    assert not compatibility.qualified_build("claude_code", "2.1.282",
                                             sys.platform, "aarch64", "sha256:abc")
    assert not compatibility.qualified_build("claude_code", "2.1.282",
                                             sys.platform, "x86_64", "sha256:other")
    assert compatibility.qualified_capabilities("claude_code", "managed", {
        "native_version": "2.1.282", "platform": sys.platform,
        "architecture": "x86_64", "fingerprint": "sha256:abc",
    }).conversation
    assert not compatibility.qualified_capabilities("claude_code", "managed", {
        "native_version": "2.1.282", "platform": sys.platform,
        "architecture": "x86_64",
    }).conversation
