import pytest

from nexus_connector_core.models import CoreError
from nexus_connector_core.one_shot import OneShotFailure, validate_one_shot_policy
from nexus_connector_core.mcp_presets import (
    compose_mcp_preset, mcp_preset_digest, render_mcp_preset, validate_mcp_preset,
)


@pytest.mark.parametrize('changes', [
    {'max_parallel': True}, {'max_parallel': -1}, {'warm_instances': 1},
    {'max_parallel': 10, 'warm_instances': 10}, {'queue_capacity': -1},
    {'queue_timeout_seconds': 0}, {'overflow': 'unlimited'}, {'other': 1},
])
def test_invalid_capacity_rejected(changes):
    with pytest.raises(CoreError):
        validate_one_shot_policy(changes)


def test_ten_parallel_five_warm():
    policy = validate_one_shot_policy({'max_parallel': 10, 'warm_instances': 5})
    assert policy.to_dict()['max_parallel'] == 10
    assert policy.to_dict()['warm_instances'] == 5


def test_unlimited_pool_preserves_explicit_warm_target():
    policy = validate_one_shot_policy({'max_parallel': 0, 'warm_instances': 4})
    assert policy.to_dict()['max_parallel'] == 0
    assert policy.warm_instances == 4


def test_unknown_effect_cannot_claim_safe_retry():
    with pytest.raises(CoreError):
        OneShotFailure('call', 'LOST', 'Lost contact.', 'execution', True, True, True)


def test_complete_replacement_and_reserved_nexus():
    inherited = {'Repo': {'url': 'https://old.example/mcp', 'headers': {'secret': 'old'}},
                 'nexus': {'url': 'bad'}}
    preset = [{'name': 'repo', 'transport': 'stdio', 'command': 'server'}]
    merged = compose_mcp_preset(inherited, preset, {'nexus': {'url': 'trusted'}}, inherit_global=True)
    assert 'Repo' not in merged
    assert 'url' not in merged['repo'] and 'headers' not in merged['repo']
    assert merged['nexus'] == {'url': 'trusted'}
    assert inherited['nexus']['url'] == 'bad'


def test_disabled_preset_removes_inherited_entry():
    assert compose_mcp_preset({'repo': {}}, [{'name': 'repo', 'enabled': False,
        'transport': 'stdio', 'command': 'server'}], {}, inherit_global=True) == {}


@pytest.mark.parametrize('entry', [
    {'name': 'nexus', 'transport': 'stdio', 'command': 'server'},
    {'name': 'repo', 'transport': 'http', 'url': 'https://user:secret@example.test/mcp'},
    {'name': 'repo', 'transport': 'http', 'url': 'https://example.test/mcp?token=secret'},
    {'name': 'repo', 'transport': 'http', 'url': 'https://example.test:bad/mcp'},
    {'name': 'repo', 'transport': 'stdio', 'command': 'server', 'env_refs': {'TOKEN': 'plaintext'}},
    {'name': 'repo', 'transport': 'stdio', 'command': 'server', 'env': {'NEXUS_TOKEN': 'value'}},
    {'name': 'repo', 'transport': 'stdio', 'command': 'server', 'args': ['bad\narg']},
    {'name': 'repo', 'transport': 'http', 'url': 'https://example.test', 'header_refs': {'Authorization': 'vault:a', 'authorization': 'vault:b'}},
])
def test_unsafe_or_invalid_preset_rejected(entry):
    with pytest.raises(CoreError):
        validate_mcp_preset([entry])


def test_duplicate_name_rejected():
    with pytest.raises(CoreError):
        validate_mcp_preset([{'name': name, 'transport': 'stdio', 'command': 'server'} for name in ['Repo', 'repo']])


def test_secret_resolution_happens_only_in_render():
    preset = [{'name': 'repo', 'transport': 'http', 'url': 'https://example.test/mcp',
               'header_refs': {'Authorization': 'vault:repo'}}]
    calls = []
    digest = mcp_preset_digest(preset)
    def resolve(ref):
        calls.append(ref)
        return 'Bearer protected'
    native = render_mcp_preset('claude_stream', preset, resolve)
    assert native['repo']['headers']['Authorization'] == 'Bearer protected'
    assert calls == ['vault:repo']
    assert 'protected' not in str(preset)
    assert digest == mcp_preset_digest(preset)


def test_pi_does_not_silently_claim_native_mcp_support():
    with pytest.raises(CoreError, match='CAPABILITY_UNSUPPORTED'):
        render_mcp_preset('pi_rpc', [], lambda ref: 'secret')
