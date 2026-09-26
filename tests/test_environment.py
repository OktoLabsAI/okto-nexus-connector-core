import asyncio
import os
from dataclasses import replace

import pytest

from nexus_connector_core import CoreError, LaunchIntent
from nexus_connector_core.discovery import candidate
from nexus_connector_core.environment import child_environment
from nexus_connector_core.harness_config import harness_http_template
from nexus_connector_core.profiles import prepare_launch


class Resolver:
    def __init__(self):
        self.calls = []

    async def resolve(self, reference):
        self.calls.append(reference)
        return "provider-local-secret"


def test_resolves_only_approved_local_ref(tmp_path, monkeypatch):
    async def run():
        binary = tmp_path / ("pi.exe" if os.name == "nt" else "pi")
        binary.write_bytes(b"test")
        if os.name != "nt":
            binary.chmod(0o755)
        prepared = prepare_launch(
            LaunchIntent("ag", "ws", "pi_rpc", auth_refs=("vault:provider-a",)),
            candidate("pi_rpc", binary, explicit=True), tmp_path)
        monkeypatch.setenv("NEXUS_OPERATOR_KEY", "admin-secret")
        monkeypatch.setenv("UNRELATED_CLOUD_KEY", "other-secret")
        resolver = Resolver()
        env = await child_environment(prepared, resolver,
                                      secret_bindings={"ANTHROPIC_API_KEY": "vault:provider-a"})
        assert resolver.calls == ["vault:provider-a"]
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(prepared, resolver,
                                    public_overrides={"HOME": str(tmp_path)})
        assert env["ANTHROPIC_API_KEY"] == "provider-local-secret"
        assert "NEXUS_OPERATOR_KEY" not in env
        assert "UNRELATED_CLOUD_KEY" not in env
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(prepared, resolver,
                                    secret_bindings={"ANTHROPIC_API_KEY": "vault:other"})
        assert resolver.calls == ["vault:provider-a"]
    asyncio.run(run())


def test_provider_home_needs_explicit_trust(tmp_path):
    async def run():
        binary = tmp_path / ("pi.exe" if os.name == "nt" else "pi")
        binary.write_bytes(b"test")
        if os.name != "nt":
            binary.chmod(0o755)
        prepared = prepare_launch(LaunchIntent("ag", "ws", "pi_rpc"),
                                  candidate("pi_rpc", binary, explicit=True), tmp_path)
        with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
            await child_environment(prepared, Resolver(), provider_home=tmp_path)
    asyncio.run(run())


def test_http_template_capability_is_resolved_only_from_approved_local_ref(
        tmp_path, monkeypatch):
    async def run():
        binary = tmp_path / ("codex.exe" if os.name == "nt" else "codex")
        binary.write_bytes(b"test")
        if os.name != "nt":
            binary.chmod(0o755)
        ref = "mcp-cap:binding-1"
        prepared = prepare_launch(
            LaunchIntent("ag", "ws", "codex_app_server", auth_refs=(ref,)),
            candidate("codex_app_server", binary, explicit=True), tmp_path)
        template = harness_http_template(
            "codex_app_server", "https://nexus.example.test/mcp", ref,
            entry_name="okto-nexus", harness_is_local=False,
            approved_origins={"https://nexus.example.test"},
            format_qualified=True)
        monkeypatch.setenv("NEXUS_OPERATOR_KEY", "admin-secret")
        resolver = Resolver()
        env = await child_environment(prepared, resolver,
                                      http_templates=(template,))
        assert env[template.bearer_env_name] == "provider-local-secret"
        assert resolver.calls == [ref]
        assert "NEXUS_OPERATOR_KEY" not in env
        assert ref not in str(env)
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(prepared, resolver,
                                    public_overrides={template.bearer_env_name: "literal"})
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(prepared, resolver,
                                    http_templates=(replace(template,
                                                            bearer_env_name="NEXUS_OPERATOR_KEY"),))
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(prepared, resolver,
                                    http_templates=(replace(template,
                                                            adapter_id="claude_stream"),))
        without_ref = prepare_launch(
            LaunchIntent("ag", "ws", "codex_app_server"),
            candidate("codex_app_server", binary, explicit=True), tmp_path)
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(without_ref, resolver,
                                    http_templates=(template,))
        assert resolver.calls == [ref]

    asyncio.run(run())


def test_missing_http_capability_fails_without_leaking_resolver_error(tmp_path):
    class MissingResolver:
        async def resolve(self, reference):
            raise RuntimeError("sensitive backend diagnostic")

    async def run():
        binary = tmp_path / ("claude.exe" if os.name == "nt" else "claude")
        binary.write_bytes(b"test")
        if os.name != "nt":
            binary.chmod(0o755)
        ref = "mcp-cap:binding-2"
        prepared = prepare_launch(
            LaunchIntent("ag", "ws", "claude_stream", auth_refs=(ref,)),
            candidate("claude_stream", binary, explicit=True), tmp_path)
        template = harness_http_template(
            "claude_stream", "https://nexus.example.test/mcp", ref,
            entry_name="okto-nexus", harness_is_local=False,
            approved_origins={"https://nexus.example.test"},
            format_qualified=True)
        with pytest.raises(CoreError, match="AGENT_AUTH_REQUIRED") as exc:
            await child_environment(prepared, MissingResolver(),
                                    http_templates=(template,))
        assert "sensitive" not in str(exc.value)

        class EmptyResolver:
            async def resolve(self, reference):
                return ""

        with pytest.raises(CoreError, match="AGENT_AUTH_REQUIRED"):
            await child_environment(prepared, EmptyResolver(),
                                    http_templates=(template,))

    asyncio.run(run())
