from dataclasses import replace
import hashlib
import pytest

from nexus_connector_core import HarnessSettings, InstallationCandidate, LaunchIntent, CoreError, validate_harness_settings
from nexus_connector_core.profiles import prepare_launch
from nexus_connector_core.harness_configuration import codex_thread_settings


@pytest.mark.parametrize('adapter,settings,expected', [
    ('claude_stream', {'effort':'high','permission_mode':'auto'}, ('--effort','high','--permission-mode','auto')),
    ('pi_rpc', {'provider':'zai','effort':'high'}, ('--provider','zai','--thinking','high')),
])
def test_native_arguments_and_profile_identity_include_settings(tmp_path,adapter,settings,expected):
    binary=tmp_path/'provider.exe'; binary.write_bytes(b'fixture')
    candidate=InstallationCandidate(adapter,str(binary),'sha256:'+hashlib.sha256(binary.read_bytes()).hexdigest(),'explicit','selected')
    intent=LaunchIntent('a','w',adapter,model='test-model',harness_settings=validate_harness_settings(adapter,settings))
    prepared=prepare_launch(intent,candidate,tmp_path)
    assert prepared.argv[-len(expected):]==expected
    assert '--model' in prepared.argv
    default=prepare_launch(replace(intent,harness_settings=HarnessSettings()),candidate,tmp_path)
    assert default.profile_fingerprint != prepared.profile_fingerprint


def test_codex_uses_native_fields_and_does_not_conflate_sandbox_and_approval():
    settings=validate_harness_settings('codex_app_server',{'effort':'high','approval_policy':'never','sandbox':'workspace-write'})
    assert codex_thread_settings(settings)=={'config':{'model_reasoning_effort':'high'},'approvalPolicy':'never','sandbox':'workspace-write'}
    assert codex_thread_settings(HarnessSettings(approval_policy='never'))=={'approvalPolicy':'never'}


@pytest.mark.parametrize('selection,enabled', [('enabled', True), ('disabled', False)])
def test_codex_default_mode_questions_preserve_reasoning_configuration(selection, enabled):
    settings = validate_harness_settings('codex_app_server', {'effort': 'low', 'user_input': selection})
    assert codex_thread_settings(settings) == {'config': {
        'model_reasoning_effort': 'low', 'features.default_mode_request_user_input': enabled}}
    with pytest.raises(CoreError):
        validate_harness_settings('pi_rpc', {'user_input': selection})


@pytest.mark.parametrize('blocking', [True, False])
def test_codex_question_contract_accepts_native_blocking_hint(blocking):
    from nexus_connector_core import native_input_response
    request = {'method': 'item/tool/requestUserInput', 'params': {
        'isBlocking': blocking, 'questions': [{'id': 'color', 'header': 'Color',
        'question': 'Choose color', 'isOther': True, 'options': [
            {'label': 'Blue', 'description': 'Blue color'},
            {'label': 'Green', 'description': 'Green color'}]}]}}
    response = {'answers': {'color': {'answers': ['Violet']}}}
    assert native_input_response(request, response, approved=True) == response


@pytest.mark.parametrize('adapter,settings',[
    ('pi_rpc',{'permission_mode':'bypassPermissions'}),
    ('claude_stream',{'provider':'zai'}),
    ('codex_app_server',{'effort':'unsupported'}),
    ('claude_stream',{'effort':True}),
    ('pi_rpc',{'provider':'bad\nvalue'}),
    ('codex_app_server',{'extra_args':'anything'}),
])
def test_settings_reject_unknown_and_cross_harness_parameters(adapter,settings):
    with pytest.raises(CoreError):validate_harness_settings(adapter,settings)
