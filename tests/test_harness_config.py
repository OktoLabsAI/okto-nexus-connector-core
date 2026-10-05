import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.harness_config import (
    direct_http_config, harness_http_template, render_codex_toml_fragment,
)
from nexus_connector_core.config_document import plan_json_entry, apply_json_plan


def test_direct_http_config_has_no_proxy_or_secret():
    config = direct_http_config("https://nexus.example.test/mcp", "secret-ref-1",
                                harness_is_local=False, supports_http=True,
                                approved_origins={"https://nexus.example.test"})
    assert config.transport == "streamable_http"
    assert config.capability_ref == "secret-ref-1"
    assert config.approved_origin == "https://nexus.example.test"
    assert not hasattr(config, "command")


@pytest.mark.parametrize("url", [
    "http://nexus.example.test/mcp", "https://user:pass@nexus.example.test/mcp",
    "https://nexus.example.test/mcp?token=secret", "http://127.0.0.1:8000/mcp",
])
def test_remote_rejects_unsafe_target(url):
    with pytest.raises(CoreError):
        direct_http_config(url, "ref", harness_is_local=False, supports_http=True,
                           approved_origins={"https://nexus.example.test",
                                             "http://127.0.0.1:8000"})


def test_local_loopback_and_stdio_only_diagnostic():
    direct_http_config("http://127.0.0.1:8000/mcp", "ref",
                       harness_is_local=True, supports_http=True,
                       approved_origins={"http://127.0.0.1:8000"},
                       loopback_reachable=True)
    with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
        direct_http_config("https://nexus.example.test/mcp", "ref",
                           harness_is_local=False, supports_http=False,
                           approved_origins={"https://nexus.example.test"})


@pytest.mark.parametrize("url", [
    "https://nexus.example.test/mcp?token=x",
    "https://nexus.example.test/mcp#fragment",
    "https://@nexus.example.test/mcp",
    "https://nexus.example.test:0/mcp",
    "https://nexus.example.test:bad/mcp",
    "https://nexus.example.test/",
    "https://nexus.example.test/\n/mcp",
    "https://nexus.example.test\\@evil.test/mcp",
    "https://2130706433/mcp",
    "https://127.000.000.001/mcp",
])
def test_reject_ambiguous_or_secret_bearing_urls(url):
    with pytest.raises(CoreError):
        direct_http_config(url, "ref", harness_is_local=False, supports_http=True,
                           approved_origins={"https://nexus.example.test"})


def test_origin_and_reachability_are_explicit():
    url = "https://nexus.example.test/mcp"
    with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
        direct_http_config(url, "ref", harness_is_local=False, supports_http=True,
                           approved_origins={"https://other.example.test"})
    with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
        direct_http_config(url, "ref", harness_is_local=False, supports_http=True,
                           approved_origins=None)
    with pytest.raises(CoreError, match="WORKSPACE_UNAVAILABLE"):
        direct_http_config("https://[::1]:8443/mcp", "ref",
                           harness_is_local=False, supports_http=True,
                           approved_origins={"https://[::1]:8443"})
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        direct_http_config("http://127.0.0.2:8000/mcp", "ref",
                           harness_is_local=True, supports_http=True,
                           approved_origins={"http://127.0.0.2:8000"})
    with pytest.raises(CoreError, match="WORKSPACE_UNAVAILABLE"):
        direct_http_config("https://localhost/mcp", "ref",
                           harness_is_local=True, supports_http=True,
                           approved_origins={"https://localhost"})
    with pytest.raises(CoreError, match="PROFILE_DRIFT"):
        direct_http_config("https://2130706433/mcp", "ref",
                           harness_is_local=False, supports_http=True,
                           approved_origins={"https://2130706433"})


@pytest.mark.parametrize("ref", ["", "Bearer secret", "https://vault/x",
                                      "ref\nother", "x" * 257])
def test_only_opaque_local_capability_refs(ref):
    with pytest.raises(CoreError, match="PROVIDER_AUTH_REQUIRED"):
        direct_http_config("https://nexus.example.test/mcp", ref,
                           harness_is_local=False, supports_http=True,
                           approved_origins={"https://nexus.example.test"})


def test_codex_direct_http_template_uses_environment_reference_not_secret():
    template = harness_http_template(
        "codex_app_server", "https://nexus.example.test/mcp", "mcp-cap:ref-1",
        entry_name="okto-nexus", harness_is_local=False,
        approved_origins={"https://nexus.example.test"}, format_qualified=True)
    assert template.section == "mcp_servers"
    assert template.entry() == {
        "url": "https://nexus.example.test/mcp",
        "bearer_token_env_var": template.bearer_env_name}
    assert template.environment_refs() == {template.bearer_env_name: "mcp-cap:ref-1"}
    assert "mcp-cap:ref-1" not in str(template.entry())
    assert "command" not in template.entry()
    assert template.bearer_env_name == harness_http_template(
        "codex_app_server", "https://nexus.example.test/mcp", "mcp-cap:ref-1",
        entry_name="okto-nexus", harness_is_local=False,
        approved_origins={"https://nexus.example.test"}, format_qualified=True
    ).bearer_env_name
    import tomllib
    parsed = tomllib.loads(render_codex_toml_fragment(template))
    assert parsed["mcp_servers"]["okto-nexus"] == template.entry()


def test_claude_direct_http_template_merges_as_owned_json_entry():
    template = harness_http_template(
        "claude_stream", "https://nexus.example.test/mcp", "mcp-cap:ref-2",
        entry_name="okto-nexus", harness_is_local=False,
        approved_origins={"https://nexus.example.test"}, format_qualified=True)
    assert template.section == "mcpServers"
    assert template.entry() == {
        "type": "http", "url": "https://nexus.example.test/mcp",
        "headers": {"Authorization": f"Bearer ${{{template.bearer_env_name}}}"}}
    source = b'{"mcpServers":{"third-party":{"command":"other"}}}'
    planned = plan_json_entry(source, section=template.section,
                              entry_name=template.entry_name,
                              proposed=template.entry())
    import json
    merged = json.loads(apply_json_plan(planned, source))
    assert merged["mcpServers"]["third-party"] == {"command": "other"}
    assert merged["mcpServers"]["okto-nexus"] == template.entry()
    assert "mcp-cap:ref-2" not in str(merged)
    with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
        render_codex_toml_fragment(template)


@pytest.mark.parametrize("adapter_id", ["pi_rpc", "claude_attach", "unknown"])
def test_unqualified_or_non_http_adapter_template_refused(adapter_id):
    with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
        harness_http_template(
            adapter_id, "https://nexus.example.test/mcp", "mcp-cap:ref",
            entry_name="okto-nexus", harness_is_local=False,
            approved_origins={"https://nexus.example.test"}, format_qualified=True)
    with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
        harness_http_template(
            "codex_app_server", "https://nexus.example.test/mcp", "mcp-cap:ref",
            entry_name="okto-nexus", harness_is_local=False,
            approved_origins={"https://nexus.example.test"}, format_qualified=False)


@pytest.mark.parametrize("name", ["", "dot.name", "../evil", "a]b", "A" * 65])
def test_template_name_is_bounded_and_safe_for_config_keys(name):
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        harness_http_template(
            "claude_stream", "https://nexus.example.test/mcp", "mcp-cap:ref",
            entry_name=name, harness_is_local=False,
            approved_origins={"https://nexus.example.test"}, format_qualified=True)


def test_http_template_rejects_provider_or_canonical_ref_namespace():
    for ref in ("vault:provider-key", "agent-key", "mcp-cap:"):
        with pytest.raises(CoreError):
            harness_http_template(
                "codex_app_server", "https://nexus.example.test/mcp", ref,
                entry_name="okto-nexus", harness_is_local=False,
                approved_origins={"https://nexus.example.test"},
                format_qualified=True)


@pytest.mark.parametrize('adapter', ['claude_stream', 'codex_app_server'])
def test_remote_http_requires_explicit_host_approval_through_process_rendering(adapter):
    from nexus_connector_core.harness_config import process_http_arguments
    kwargs = dict(entry_name='nexus', harness_is_local=False,
                  approved_origins={'http://192.168.0.146:8202'}, format_qualified=True)
    url = 'http://192.168.0.146:8202/mcp'
    with pytest.raises(CoreError, match='PROFILE_DRIFT'):
        harness_http_template(adapter, url, 'mcp-cap:one', **kwargs)
    template = harness_http_template(adapter, url, 'mcp-cap:one',
                                     allow_remote_http=True, **kwargs)
    assert url in ' '.join(process_http_arguments(adapter, (template,), {'mcp-cap:one'}))
    with pytest.raises(CoreError, match='BINDING_NOT_AUTHORIZED'):
        harness_http_template(adapter, 'http://other.test/mcp', 'mcp-cap:one',
                              allow_remote_http=True, **kwargs)
