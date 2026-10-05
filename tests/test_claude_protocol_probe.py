import json
import pytest

from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.adapter_types import NativeAdapterError


@pytest.mark.parametrize('outcome', ['success', 'error', 'wrong_id', 'malformed', 'timeout'])
def test_initialize_requires_correlated_success(outcome):
    connector = ClaudeCodeStreamConnector(binary='unused')
    connector._emit = lambda *args: None
    sent = []
    def write(frame):
        sent.append(frame)
        if outcome == 'timeout':
            return
        connector._handle_stdout_line(json.dumps({'type': 'control_response', 'response': {
            'request_id': 'other' if outcome == 'wrong_id' else frame['request_id'],
            'subtype': 'error' if outcome == 'error' else 'success',
            'response': None if outcome == 'malformed' else {'commands': [], 'models': []}}}))
    connector._write_json = write
    if outcome == 'success':
        connector.verify_protocol(timeout=.01)
    else:
        with pytest.raises(NativeAdapterError):
            connector.verify_protocol(timeout=.01)
    assert len(sent) == 1 and sent[0]['request']['subtype'] == 'initialize'
    assert connector._initialize_probe is None


@pytest.mark.parametrize('architecture', ['x86_64', 'aarch64'])
def test_observed_build_can_attempt_protocol_without_recorded_hash(architecture):
    from nexus_connector_core.native.adapters.compatibility import can_probe_protocol, qualified_build
    fingerprint = 'sha256:' + 'f' * 64
    assert not qualified_build('claude_code', '2.1.999', 'darwin', architecture, fingerprint)
    assert can_probe_protocol('2.1.999', architecture, fingerprint)
    assert not can_probe_protocol(None, architecture, fingerprint)
    assert not can_probe_protocol('unrecognized', architecture, fingerprint)
    assert not can_probe_protocol('2.1.999', None, fingerprint)
    assert not can_probe_protocol('2.1.999', architecture, 'missing')
