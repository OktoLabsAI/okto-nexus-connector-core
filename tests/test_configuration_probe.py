import os
import sys
from types import SimpleNamespace
import pytest

from nexus_connector_core import CoreError
from nexus_connector_core import configuration_probe as probe


@pytest.mark.parametrize('output,success', [
    ("import sys;sys.stderr.write('x'*20000);print('  --effort <level> (low, high)')", True),
    ("print('x'*150000)", False),
    ("raise SystemExit(2)", False),
])
def test_help_probe_drains_pipes_and_rejects_overflow_or_failure(tmp_path, monkeypatch, output, success):
    actual_spawn = probe.spawn_owned_process
    def spawn(argv, **options):
        assert argv == [sys.executable, '--help']
        assert 'PROVIDER_SECRET' not in options['env']
        return actual_spawn([sys.executable, '-c', output], **options)
    monkeypatch.setattr(probe, 'spawn_owned_process', spawn)
    monkeypatch.setattr(probe, 'selected_fingerprint', lambda c:'fingerprint')
    candidate = SimpleNamespace(adapter_id='claude_stream', trust='selected',
        fingerprint='fingerprint', executable=sys.executable, version='test', installation_ref='selected')
    env={**os.environ,'PROVIDER_SECRET':'must-not-be-passed'}
    if success:
        result=probe.probe_selected_configuration(candidate,cwd=tmp_path,env=env)
        assert result['parameters'][1]['values'] == ['low','high']
    else:
        with pytest.raises(CoreError):
            probe.probe_selected_configuration(candidate,cwd=tmp_path,env=env)


def test_help_probe_refuses_drift_before_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'selected_fingerprint', lambda c:'changed')
    monkeypatch.setattr(probe, 'spawn_owned_process', lambda *a,**k:pytest.fail('must not spawn'))
    candidate = SimpleNamespace(adapter_id='claude_stream', trust='selected',fingerprint='original')
    with pytest.raises(CoreError, match='PROFILE_DRIFT'):
        probe.probe_selected_configuration(candidate,cwd=tmp_path,env={})
