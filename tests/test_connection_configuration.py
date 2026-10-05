import json
import pytest
from nexus_connector_core import CoreError
from nexus_connector_core.connection_configuration import (parse_connection_configuration, export_connection_configuration,
    parse_portable_connection_configuration, materialize_connection_configuration, DESTINATION_FIELDS)


def configuration():
    return dict(format='okto-nexus-connection',version=1,adapter_id='pi_rpc',execution_location='local',
        runtime_enabled=True,session_policy='per_sender',workspace_root='/work/project',workspace_label='Project',
        provider_home='/home/test/.pi/agent',secret_bindings={'TOKEN':'vault:provider-key'},alias='pi',
        harness_settings={'model':'glm-5.3','provider':'zai','effort':'low'},automatic_reply=True,
        tool_access='always_allow',authorization={'minutes':None,'actions':None})


def test_legacy_reply_switch_cannot_disable_runtime_routing():
    value=configuration()
    value['automatic_reply']=False
    assert parse_connection_configuration(value)['automatic_reply'] is True
    assert json.loads(export_connection_configuration(value))['automatic_reply'] is True
    assert value['automatic_reply'] is False


@pytest.mark.parametrize('enabled',[True,False,None])
@pytest.mark.parametrize('policy',['shared','per_sender','per_sender_session',None])
def test_roundtrip_preserves_complete_configuration(enabled, policy):
    value=configuration()
    value['runtime_enabled']=enabled
    value['session_policy']=policy
    exported=json.loads(export_connection_configuration(value))
    assert exported['version']==2
    assert not DESTINATION_FIELDS.intersection(exported)
    assert parse_portable_connection_configuration(exported)==parse_portable_connection_configuration(value)
    materialized=materialize_connection_configuration(exported,workspace_root='/destination')
    assert materialized['workspace_root']=='/destination'
    assert materialized['provider_home'] is None
    assert materialized['secret_bindings']=={}
    assert materialized['runtime_enabled']==enabled
    assert materialized['session_policy']==policy


def test_legacy_import_discards_machine_choices():
    assert not DESTINATION_FIELDS.intersection(parse_portable_connection_configuration(configuration()))


def test_portable_import_rejects_host_fields_and_credentials():
    value=parse_portable_connection_configuration(configuration())
    for key in (*DESTINATION_FIELDS,'candidate_ref','agent_id','api_key'):
        with pytest.raises(CoreError):parse_portable_connection_configuration({**value,key:'unexpected'})
    with pytest.raises(ValueError):parse_portable_connection_configuration('{"version":2,"version":1}')


@pytest.mark.parametrize('changes',[
    {'execution_location':'all'},
    {'api_key':'secret'}, {'secret_bindings':{'TOKEN':'raw-secret'}}, {'authorization':{'minutes':True,'actions':10}},
    {'harness_settings':{'model':'bad\x00model'}}, {'version':True}, {'tool_access':'invalid'},
])
def test_reject_invalid_and_credential_fields(changes):
    with pytest.raises(CoreError): parse_connection_configuration(configuration() | changes)
