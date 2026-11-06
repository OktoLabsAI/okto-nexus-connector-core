"""External participant plans preserve host ownership and managed boundaries."""
from dataclasses import replace
import json
import tomllib

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.config_document import apply_json_plan, apply_toml_plan
from nexus_connector_core.config_persistence import apply_json_plan_file, apply_toml_plan_file
from nexus_connector_core.harness_config import harness_http_template, process_http_arguments
from nexus_connector_core.participant_config import (
    ParticipantClientConfig, export_participant_config, participant_client_config,
    plan_participant_config, plan_participant_removal,
)


def configuration(client='claude', **changes):
    return participant_client_config(**(dict(client=client, client_version='1.2.3',
        server_url='https://nexus.example/mcp', approved_origin='https://nexus.example',
        entry_name='nexus-review', credential_environment='NEXUS_PARTICIPANT_TOKEN_REVIEW',
        file_scope='project') | changes))


@pytest.mark.parametrize('client', ['claude', 'codex'])
def test_unobserved_build_is_explicitly_unknown_without_inventing_qualification(client):
    config = configuration(client, client_version=None)
    assert config.to_dict()['client_version'] is None
    assert config.credential_environment in export_participant_config(config)
    assert plan_participant_config(None, config).changed


@pytest.mark.parametrize('client', ['claude', 'codex'])
def test_reference_only_round_trip_and_selected_entry_ownership(client, tmp_path):
    config = configuration(client)
    source = ('{"model":"personalized","mcpServers":{"other":{"command":"not executed"}},"note":"ação"}\n'.encode()
        if client == 'claude' else '# keep ação\r\nmodel = "personalized"\r\n[mcp_servers.other]\r\ncommand = "not executed"\r\n'.encode())
    path = tmp_path / ('project with espaços.json' if client == 'claude' else 'project with espaços.toml')
    path.write_bytes(source)
    apply = apply_json_plan_file if client == 'claude' else apply_toml_plan_file
    parse = json.loads if client == 'claude' else lambda data: tomllib.loads(data.decode())
    section = 'mcpServers' if client == 'claude' else 'mcp_servers'
    plan = plan_participant_config(source, config)
    assert path.read_bytes() == source  # Planning has no filesystem effects.
    result = apply(plan, path)
    assert result.backup_path.read_bytes() == source
    current = path.read_bytes()
    assert parse(current)[section]['nexus-review'] == config.entry()
    assert parse(current)[section]['other'] == {'command': 'not executed'}
    assert parse(current)['model'] == 'personalized'
    if client == 'codex':
        assert current.startswith(source) and b'\r\nurl' in current
    with pytest.raises(CoreError, match='APPROVAL_REQUIRED'):
        plan_participant_config(current, config)
    same = plan_participant_config(current, config, previously_owned=config.entry())
    assert not apply(same, path).changed
    assert len(list(tmp_path.glob('*.bak'))) == 1
    with pytest.raises(CoreError, match='PROFILE_DRIFT'):
        apply(plan, path)
    # Removal changes only the owned entry, preserving another user's edit.
    edited = current.replace(b'personalized', b'edited later')
    path.write_bytes(edited)
    removal = plan_participant_removal(edited, config, previously_owned=config.entry())
    apply(removal, path)
    assert parse(path.read_bytes())[section]['other'] == {'command': 'not executed'}
    assert parse(path.read_bytes())['model'] == 'edited later'
    assert 'nexus-review' not in parse(path.read_bytes())[section]


@pytest.mark.parametrize('client', ['claude', 'codex'])
def test_changed_owned_entry_and_stale_review_are_refused(client):
    config = configuration(client)
    apply = apply_json_plan if client == 'claude' else apply_toml_plan
    source = apply(plan_participant_config(None, config), None)
    changed = source.replace(b'nexus.example', b'edited.example')
    with pytest.raises(CoreError, match='PROFILE_DRIFT'):
        plan_participant_config(changed, config, previously_owned=config.entry())
    with pytest.raises(CoreError, match='PROFILE_DRIFT'):
        plan_participant_removal(changed, config, previously_owned=config.entry())
    new_config = replace(config, credential_environment='NEXUS_PARTICIPANT_TOKEN_NEW')
    plan = plan_participant_config(source, new_config, previously_owned=config.entry())
    with pytest.raises(CoreError, match='PROFILE_DRIFT'):
        apply(plan, source + b'\n')
    assert new_config.credential_environment.encode() in apply(plan, source)


@pytest.mark.parametrize('client,source', [
    ('claude', b'{"mcpServers":{},"mcpServers":{}}'),
    ('claude', b'{"number":NaN}'), ('claude', b'[]'), ('claude', b'\xff'),
    ('codex', b'model="a"\nmodel="b"'), ('codex', b'[broken'),
    ('codex', b'mcp_servers="not a table"'),
])
def test_invalid_or_duplicate_documents_fail_without_rewriting(client, source):
    with pytest.raises(CoreError, match='PROFILE_DRIFT'):
        plan_participant_config(source, configuration(client))


@pytest.mark.parametrize('changes', [
    dict(credential_environment='nxs_' + 'a' * 64),
    dict(credential_environment='mcp-cap:session'), dict(credential_environment='ANTHROPIC_AUTH_TOKEN'),
    dict(credential_environment='NEXUS_PARTICIPANT_TOKEN_X\nATTACK'),
    dict(server_url='https://nexus.example/mcp?token=private'),
    dict(server_url='https://user:private@nexus.example/mcp'),
    dict(server_url='https://elsewhere.example/mcp'),
    dict(server_url='https://nexus.example/mcp\n'),
    dict(server_url='https://nexus.example/api'),
    dict(server_url='http://nexus.example/mcp', approved_origin='http://nexus.example'),
    dict(server_url='http://127.0.0.1:8000/mcp', approved_origin='http://127.0.0.1:8000'),
    dict(entry_name='name]injection'), dict(client_version='not verified'), dict(file_scope='machine'),
])
def test_invalid_reference_origin_version_and_scope_are_rejected(changes):
    with pytest.raises(CoreError):
        configuration(**changes)


def test_transport_exceptions_are_explicit_and_do_not_imply_authentication():
    local = configuration(server_url='http://127.0.0.1:8000/mcp',
        approved_origin='http://127.0.0.1:8000', loopback_reachable=True)
    remote = configuration(server_url='http://nexus.example/mcp',
        approved_origin='http://nexus.example', allow_remote_http=True)
    assert local.entry()['type'] == remote.entry()['type'] == 'http'
    assert ParticipantClientConfig(**local.to_dict()) == local
    with pytest.raises(CoreError):
        replace(local, format_revision=True)
    with pytest.raises(CoreError):
        replace(local, format='codex-config-toml')


def test_generic_export_is_manual_and_pi_has_no_invented_http_adapter():
    config = configuration('generic', client_version=None, file_scope='manual')
    output = json.loads(export_participant_config(config))
    assert output['state'] == 'manual_configuration_required'
    assert output['connection']['authentication']['reference']['name'] == config.credential_environment
    with pytest.raises(CoreError, match='CAPABILITY_UNSUPPORTED'):
        plan_participant_config(None, config)
    with pytest.raises(CoreError, match='CAPABILITY_UNSUPPORTED'):
        configuration('pi')


def test_participant_contract_cannot_substitute_for_managed_capability_or_qualification():
    config = configuration()
    for reference, qualified in [('nxs_' + 'a' * 64, True), ('mcp-cap:one', False)]:
        with pytest.raises(CoreError):
            harness_http_template('claude_stream', config.server_url, reference,
                entry_name=config.entry_name, harness_is_local=False,
                approved_origins={config.approved_origin}, format_qualified=qualified)
    with pytest.raises(CoreError):
        process_http_arguments('claude_stream', (config,), {})
    managed = harness_http_template('claude_stream', config.server_url, 'mcp-cap:one',
        entry_name=config.entry_name, harness_is_local=False,
        approved_origins={config.approved_origin}, format_qualified=True)
    with pytest.raises(CoreError):
        plan_participant_config(None, managed)
