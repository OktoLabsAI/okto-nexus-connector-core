from pathlib import Path
import pytest
from nexus_connector_core import discover_provider_home


@pytest.mark.parametrize('adapter,variable,suffix', [
    ('codex_app_server', 'CODEX_HOME', '.codex'),
    ('claude_stream', 'CLAUDE_CONFIG_DIR', '.claude'),
    ('pi_rpc', 'PI_CODING_AGENT_DIR', '.pi/agent'),
])
def test_home_discovery_defaults_overrides_and_missing(adapter, variable, suffix, tmp_path):
    assert discover_provider_home(adapter, home=tmp_path, environ={}) is None
    expected = tmp_path / suffix
    expected.mkdir(parents=True)
    assert discover_provider_home(adapter, home=tmp_path, environ={}) == str(expected.resolve())
    custom = tmp_path / 'custom'
    custom.mkdir()
    assert discover_provider_home(adapter, home=tmp_path, environ={variable: str(custom)}) == str(custom.resolve())
    # A broken override must not silently select a different account.
    for invalid in ('relative/path', str(tmp_path / 'missing')):
        assert discover_provider_home(adapter, home=tmp_path, environ={variable: invalid}) is None
    assert list(custom.iterdir()) == []  # discovery neither creates nor reads login material


def test_unknown_harness_has_no_suggestion(tmp_path):
    assert discover_provider_home('unknown', home=tmp_path, environ={}) is None
