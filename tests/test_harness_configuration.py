import pytest

from nexus_connector_core import CoreError, discover_harness_configuration
from nexus_connector_core import query_harness_configuration
from nexus_connector_core import validate_harness_configuration


@pytest.mark.parametrize('adapter', ['codex_app_server', 'claude_stream', 'pi_rpc'])
def test_passive_discovery_does_not_invent_observed_models_or_native_support(adapter):
    result = discover_harness_configuration(adapter, version='unknown')
    assert result['models'] == []
    assert all(p['availability'] != 'observed' for p in result['parameters'])
    assert all(p['core_applies'] for p in result['parameters'])
    assert result['human_input']['separate_from_tool_approval']
    assert result['nexus_tool_approval']['scope'] == 'nexus_tools_only'
    assert result == discover_harness_configuration(adapter, version='unknown')
    result['parameters'].clear()
    assert discover_harness_configuration(adapter)['parameters']


def test_codex_catalog_preserves_model_specific_effort_without_raw_provider_data():
    result = discover_harness_configuration('codex_app_server', native_models={'data': [
        {'id': 'picker-id', 'model': 'model-a', 'supportedReasoningEfforts': [
            {'reasoningEffort': 'low'}, {'reasoningEffort': 'high'}],
         'defaultReasoningEffort': 'high', 'unrelated': 'do not publish'}]})
    assert result['models'] == [dict(id='model-a', provider=None, efforts=['low','high'], default_effort='high')]
    assert 'do not publish' not in str(result)
    assert result['parameters'][0]['availability'] == 'observed'


def test_pi_provider_identity_and_observed_thinking_levels():
    result = discover_harness_configuration('pi_rpc', native_models={'models': [
        {'id': 'same-model', 'provider': 'one'}, {'id': 'same-model', 'provider': 'two'}]},
        thinking_levels={'levels': ['off','high']})
    assert [m['provider'] for m in result['models']] == ['one', 'two']
    assert result['parameters'][-1]['values'] == ['off','high']
    assert result['human_input']['core_bridge'] == 'implemented_version_qualification_required'


def test_claude_uses_observed_cli_choices_not_latest_documentation():
    result = discover_harness_configuration('claude_stream', cli_help='''Options:
  --model <model> Model ID
  --effort <level> Effort for this session
                    (low, medium, high)
  --permission-mode <mode> Permission mode (choices: "default", "auto")
  --verbose Enable logs
''')
    assert result['parameters'][1]['values'] == ['low','medium','high']
    assert result['parameters'][2]['values'] == ['default','auto']
    assert all(p['availability'] == 'observed' for p in result['parameters'] if p['name'] != 'inherit_global_mcps')
    assert next(p for p in result['parameters'] if p['name'] == 'inherit_global_mcps')['availability'] == 'core_contract'


@pytest.mark.parametrize('kwargs', [
    {'native_models': {'data': 'invalid'}},
    {'native_models': {'data': [{'model':'x','supportedReasoningEfforts': [],'defaultReasoningEffort':'high'}]}},
    {'native_models': {'data': [{'model':'x'},{'model':'x'}]}},
    {'thinking_levels': {'levels':['high']}},
    {'cli_help': 'unexpected'},
])
def test_rejects_invalid_or_wrong_provider_observations(kwargs):
    with pytest.raises(CoreError):
        discover_harness_configuration('codex_app_server', **kwargs)


@pytest.mark.asyncio
async def test_native_discovery_reads_all_pages_without_starting_a_turn():
    calls = []
    async def request(method, params):
        calls.append((method, params))
        return {'data':[{'model': 'second' if params.get('cursor') else 'first'}],
                'nextCursor':None if params.get('cursor') else 'next'}
    result = await query_harness_configuration('codex_app_server', request)
    assert [m['id'] for m in result['models']] == ['first', 'second']
    assert [c[0] for c in calls] == ['model/list','model/list']


@pytest.mark.asyncio
async def test_native_discovery_rejects_repeated_cursor_and_propagates_disconnect():
    async def repeated(method, params):
        return {'data':[], 'nextCursor':'same'}
    with pytest.raises(CoreError):
        await query_harness_configuration('codex_app_server', repeated)
    async def disconnected(method, params):
        raise ConnectionError('offline')
    with pytest.raises(ConnectionError):
        await query_harness_configuration('pi_rpc', disconnected)


def test_observed_model_requires_its_own_effort():
    schema = discover_harness_configuration('codex_app_server', native_models={'data': [
        {'model':'small', 'supportedReasoningEfforts':[{'reasoningEffort':'low'}]},
        {'model':'large', 'supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]})
    assert validate_harness_configuration(schema, {'model':'small', 'effort':'low'})
    with pytest.raises(CoreError):
        validate_harness_configuration(schema, {'model':'small', 'effort':'high'})
    with pytest.raises(CoreError):
        validate_harness_configuration(schema, {'model':None})


def test_pi_duplicate_model_requires_provider_and_options_are_unique():
    schema = discover_harness_configuration('pi_rpc', native_models={'models':[
        {'id':'shared', 'provider':'a'}, {'id':'shared', 'provider':'b'},
        {'id':'only-a', 'provider':'a'}]})
    assert schema['parameters'][0]['values'] == ['shared','only-a']
    assert schema['parameters'][1]['values'] == ['a','b']
    assert validate_harness_configuration(schema, {'model':'shared','provider':'b'})
    for invalid in [{'model':'shared'}, {'model':'only-a','provider':'b'}]:
        with pytest.raises(CoreError):
            validate_harness_configuration(schema, invalid)


@pytest.mark.asyncio
async def test_managed_requirements_restrict_choices_and_do_not_imply_an_approval():
    calls = []
    async def request(method, params):
        calls.append(method)
        return ({'data':[]} if method == 'model/list' else {'requirements':{
            'allowedApprovalPolicies':['never'], 'allowedSandboxModes':[],
            'unrelated':'do not publish'}})
    schema = await query_harness_configuration('codex_app_server', request, include_requirements=True)
    assert calls == ['model/list','configRequirements/read']
    assert schema['constraints'] == {'approval_policy':['never'],'sandbox':[]}
    assert schema['parameters'][3]['values'] == []
    assert 'do not publish' not in str(schema)
    with pytest.raises(CoreError):
        validate_harness_configuration(schema, {'approval_policy':'never','sandbox':'read-only'})
    with pytest.raises(CoreError):
        validate_harness_configuration(schema, {})


@pytest.mark.parametrize('row', [{'id':'x'}, {'id':'x','provider':''}, {'id':'x\n','provider':'p'}])
def test_pi_rejects_unusable_model_identity(row):
    with pytest.raises(CoreError):
        discover_harness_configuration('pi_rpc', native_models={'models':[row]})
