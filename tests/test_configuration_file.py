import json
import pytest
from nexus_connector_core import (CoreError, discover_harness_configuration,
    parse_harness_configuration_file, export_harness_configuration_file)


@pytest.mark.parametrize('adapter,settings', [
    ('codex_app_server', {'model':'gpt-6.1-sol', 'effort':'low', 'user_input':'enabled', 'approval_policy':'on-request'}),
    ('claude_stream', {'model':'sonnet', 'effort':'low', 'permission_mode':'default'}),
    ('pi_rpc', {'model':'glm-5.3', 'provider':'zai', 'effort':'low'}),
])
def test_portable_round_trip(adapter, settings):
    document = export_harness_configuration_file(adapter, settings)
    assert parse_harness_configuration_file(json.dumps(document), adapter_id=adapter)['settings'] == settings


@pytest.mark.parametrize('change', [
    {'version':True}, {'version':2}, {'settings':{'api_key':'secret'}},
    {'settings':{'effort':'invented'}}, {'settings':{'effort':None}},
    {'credentials':{}}, {'configuration':{}}, {'settings':[]},
])
def test_file_cannot_introduce_unknown_values_or_authority(change):
    document = export_harness_configuration_file('pi_rpc', {})
    document.update(change)
    with pytest.raises(CoreError):
        parse_harness_configuration_file(json.dumps(document))


def test_observed_model_and_adapter_constraints():
    document = export_harness_configuration_file('pi_rpc', {'model':'absent'})
    with pytest.raises(CoreError):
        parse_harness_configuration_file(json.dumps(document), adapter_id='claude_stream')
    schema = discover_harness_configuration('pi_rpc', native_models={'models':[{'id':'known', 'provider':'zai'}]})
    with pytest.raises(CoreError):
        parse_harness_configuration_file(json.dumps(document), configuration=schema)


@pytest.mark.parametrize('text', ['{', '[]', ' ' * 65537,
    '{"format":"nexus-harness-config","version":1,"adapter_id":"pi_rpc","settings":{},"settings":{}}'],
    ids=['syntax', 'array', 'oversize', 'duplicate'])
def test_malformed_or_ambiguous_file(text):
    with pytest.raises(CoreError):
        parse_harness_configuration_file(text)
