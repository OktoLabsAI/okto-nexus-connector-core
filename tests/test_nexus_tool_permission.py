import json
import tomllib
import pytest
from nexus_connector_core.harness_config import harness_http_template, process_http_arguments, render_codex_toml_fragment


def template(adapter, allow):
    return harness_http_template(adapter, 'http://127.0.0.1:8202/mcp', 'mcp-cap:test', entry_name='nexus_test',
        harness_is_local=True, approved_origins={'http://127.0.0.1:8202'}, loopback_reachable=True,
        format_qualified=True, always_allow_tools=allow)


@pytest.mark.parametrize('allow', [False, True])
def test_codex_permission_is_server_scoped_in_process_and_home(allow):
    t = template('codex_app_server', allow)
    fragment = tomllib.loads(render_codex_toml_fragment(t))
    args = process_http_arguments(t.adapter_id, (t,), (t.capability_ref,))
    process = tomllib.loads(args[1])
    assert process == fragment
    assert fragment['mcp_servers']['nexus_test'].get('default_tools_approval_mode') == ('approve' if allow else None)
    assert 'approvalPolicy' not in args[1] and 'sandbox' not in args[1]


@pytest.mark.parametrize('allow', [False, True])
def test_claude_permission_only_matches_generated_nexus_server(allow):
    t = template('claude_stream', allow)
    args = process_http_arguments(t.adapter_id, (t,), (t.capability_ref,))
    assert set(json.loads(args[2])['mcpServers']) == {'nexus_test'}
    assert args[3:] == (('--allowedTools', 'mcp__nexus_test__*') if allow else ())
    assert '--dangerously-skip-permissions' not in args
