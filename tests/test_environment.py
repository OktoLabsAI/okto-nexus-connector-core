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


def test_pi_configuration_directory_is_explicit_and_not_inherited(tmp_path, monkeypatch):
    async def run():
        binary = tmp_path / ("pi.exe" if os.name == "nt" else "pi")
        binary.write_bytes(b"test")
        if os.name != "nt":
            binary.chmod(0o755)
        prepared = prepare_launch(LaunchIntent("ag", "ws", "pi_rpc"),
                                  candidate("pi_rpc", binary, explicit=True), tmp_path)
        home = tmp_path / "approved-agent-dir"
        home.mkdir()
        (home / "settings.json").write_text('{"defaultProvider":"test"}')
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "unapproved"))
        assert "PI_CODING_AGENT_DIR" not in await child_environment(prepared, Resolver())
        with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
            await child_environment(prepared, Resolver(), provider_home=home)
        env = await child_environment(prepared, Resolver(), provider_home=home, trusted_home=True)
        assert env["PI_CODING_AGENT_DIR"] == str(home.resolve())
        assert (home / "settings.json").read_text() == '{"defaultProvider":"test"}'
        assert not (home / ".pi").exists()
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(prepared, Resolver(), provider_home=home, trusted_home=True,
                                    public_overrides={"PI_CODING_AGENT_DIR": str(tmp_path)})
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


@pytest.mark.parametrize("existing", [False, True])
def test_codex_uses_only_explicitly_approved_provider_home(tmp_path, monkeypatch, existing):
    async def run():
        binary = tmp_path / ("codex.exe" if os.name == "nt" else "codex")
        binary.write_bytes(b"test")
        if os.name != "nt":
            binary.chmod(0o755)
        prepared = prepare_launch(LaunchIntent("ag", "ws", "codex_app_server"),
                                  candidate("codex_app_server", binary, explicit=True), tmp_path)
        home = tmp_path / "approved"
        home.mkdir()
        state = home / ".codex"
        if existing:
            state.mkdir()
            (state / "config.toml").write_text("# Existing configuration\n")
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "unapproved"))
        with pytest.raises(CoreError, match="APPROVAL_REQUIRED"):
            await child_environment(prepared, Resolver(), provider_home=home)
        assert state.exists() is existing
        env = await child_environment(prepared, Resolver(), provider_home=home, trusted_home=True)
        assert env["CODEX_HOME"] == str(state.resolve())
        assert state.is_dir()
        if existing:
            assert (state / "config.toml").read_text() == "# Existing configuration\n"
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await child_environment(prepared, Resolver(), provider_home=home, trusted_home=True,
                                    public_overrides={"CODEX_HOME": str(tmp_path)})
    asyncio.run(run())


def test_codex_invalid_state_directory_fails_without_path_disclosure(tmp_path):
    async def run():
        binary = tmp_path / ("codex.exe" if os.name == "nt" else "codex")
        binary.write_bytes(b"test")
        if os.name != "nt":
            binary.chmod(0o755)
        prepared = prepare_launch(LaunchIntent("ag", "ws", "codex_app_server"),
                                  candidate("codex_app_server", binary, explicit=True), tmp_path)
        (tmp_path / ".codex").write_text("not a directory")
        with pytest.raises(CoreError, match="WORKSPACE_UNAVAILABLE") as error:
            await child_environment(prepared, Resolver(), provider_home=tmp_path, trusted_home=True)
        assert str(tmp_path) not in str(error.value)
    asyncio.run(run())


@pytest.mark.parametrize('adapter,state_name,variable', [
    ('codex_app_server', '.codex', 'CODEX_HOME'),
    ('claude_stream', '.claude', 'CLAUDE_CONFIG_DIR'),
])
def test_discovered_configuration_directory_is_used_directly(tmp_path, adapter, state_name, variable):
    async def run():
        binary = tmp_path / ('test.exe' if os.name == 'nt' else 'test')
        binary.write_bytes(b'test')
        if os.name != 'nt':
            binary.chmod(0o755)
        prepared = prepare_launch(LaunchIntent('ag', 'ws', adapter),
                                  candidate(adapter, binary, explicit=True), tmp_path)
        state = tmp_path / state_name
        state.mkdir()
        env = await child_environment(prepared, Resolver(), provider_home=state, trusted_home=True)
        assert env[variable] == str(state.resolve())
        assert not (state / state_name).exists()
    asyncio.run(run())


def _claude_prepared(tmp_path):
    binary = tmp_path / ('claude.exe' if os.name == 'nt' else 'claude')
    binary.write_bytes(b'test')
    if os.name != 'nt':
        binary.chmod(0o755)
    return prepare_launch(LaunchIntent('ag', 'ws', 'claude_stream'),
                          candidate('claude_stream', binary, explicit=True), tmp_path)


def test_default_claude_state_keeps_account_home_and_keychain_lookup(tmp_path, monkeypatch):
    # Claude Code finds its macOS Keychain login only with the real HOME,
    # $USER and no CLAUDE_CONFIG_DIR; redirecting any of them logs it out.
    async def run():
        account = tmp_path / 'account'
        (account / '.claude').mkdir(parents=True)
        monkeypatch.setenv('HOME', str(account))
        monkeypatch.setenv('USERPROFILE', str(account))
        monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
        monkeypatch.setenv('USER', 'operator')
        monkeypatch.setenv('LOGNAME', 'operator')
        env = await child_environment(_claude_prepared(tmp_path), Resolver(),
                                      provider_home=account / '.claude', trusted_home=True)
        assert env['HOME'] == str(account.resolve())
        assert env['USERPROFILE'] == env['HOME']
        assert 'CLAUDE_CONFIG_DIR' not in env
        assert env['USER'] == env['LOGNAME'] == 'operator'
    asyncio.run(run())


def test_custom_claude_state_is_still_bound_through_config_dir(tmp_path, monkeypatch):
    async def run():
        account = tmp_path / 'account'
        (account / '.claude').mkdir(parents=True)
        custom = tmp_path / 'other-claude'
        custom.mkdir()
        monkeypatch.setenv('HOME', str(account))
        monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
        env = await child_environment(_claude_prepared(tmp_path), Resolver(),
                                      provider_home=custom, trusted_home=True)
        assert env['HOME'] == str(custom.resolve())
        assert env['CLAUDE_CONFIG_DIR'] == str(custom.resolve())
    asyncio.run(run())


def test_daemon_claude_config_override_is_not_treated_as_default(tmp_path, monkeypatch):
    async def run():
        account = tmp_path / 'account'
        state = account / '.claude'
        state.mkdir(parents=True)
        monkeypatch.setenv('HOME', str(account))
        monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(state))
        env = await child_environment(_claude_prepared(tmp_path), Resolver(),
                                      provider_home=state, trusted_home=True)
        assert env['CLAUDE_CONFIG_DIR'] == str(state.resolve())
    asyncio.run(run())

