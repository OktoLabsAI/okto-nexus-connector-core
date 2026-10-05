import pytest
from nexus_connector_core import CoreError, InstallationCandidate
from nexus_connector_core.discovery import fingerprint
import nexus_connector_core.protocol_probe as probe


@pytest.mark.parametrize('adapter_id', ['claude_stream', 'codex_app_server', 'pi_rpc'])
@pytest.mark.parametrize('result', ['success', 'rejected', 'cleanup_unknown'])
def test_protocol_probe_isolated_and_requires_cleanup(tmp_path, monkeypatch, adapter_id, result):
    executable = tmp_path / 'native'
    executable.write_bytes(b'synthetic selected executable')
    candidate = InstallationCandidate(adapter_id, str(executable), fingerprint(executable), 'explicit', 'selected')
    calls = []
    class Adapter:
        def __init__(self, **kwargs):
            env = kwargs['env']
            assert 'API_KEY' not in env and 'NEXUS_OPERATOR_KEY' not in env
            assert env['HOME'] != 'original-home'
            assert kwargs['cwd'] == env['HOME']
        def start(self, **kwargs):
            calls.append('start')
            self._launch_guard('start')
            if result == 'rejected':
                raise RuntimeError('malformed handshake')
        def verify_protocol(self): calls.append('initialize')
        def close(self):
            calls.append('close')
            return 'unknown' if result == 'cleanup_unknown' else 'graceful'
    monkeypatch.setattr(probe, 'load_adapter', lambda _: Adapter)
    monkeypatch.setattr(probe, 'require_containment', lambda: None)
    env = {'HOME': 'original-home', 'API_KEY': 'secret', 'NEXUS_OPERATOR_KEY': 'secret'}
    if result == 'success':
        assert probe.probe_selected_protocol(candidate, env=env)['protocol_verified']
    else:
        with pytest.raises(CoreError, match='CONTAINMENT_UNCONFIRMED' if result == 'cleanup_unknown' else 'NATIVE_PROTOCOL_INCOMPATIBLE'):
            probe.probe_selected_protocol(candidate, env=env)
    assert calls[0] == 'start' and calls[-1] == 'close'
    assert ('initialize' in calls) == (adapter_id == 'claude_stream' and result != 'rejected')
