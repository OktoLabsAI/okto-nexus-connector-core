"""Pure external participant configuration, separate from managed capabilities.

No credential value, filesystem access, HTTP client or process launcher belongs
in this contract. Hosts select files, authenticate the existing identity, resolve
credentials in the client's actual context and perform reviewed persistence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from .config_document import (
    JsonConfigPlan, TomlConfigPlan, _plan_codex_entry, plan_json_entry,
    plan_codex_toml_entry_removal, plan_json_entry_removal,
)
from .harness_config import _origin
from .models import CoreError

PARTICIPANT_CONFIG_REVISION = 1
_FORMATS = {'claude': 'claude-mcp-json', 'codex': 'codex-config-toml',
            'generic': 'manual-http-json'}
_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z', re.ASCII)
_ENV = re.compile(r'NEXUS_PARTICIPANT_TOKEN_[A-Z0-9_]{1,64}\Z', re.ASCII)
_VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?\Z', re.ASCII)


@dataclass(frozen=True, slots=True)
class ParticipantClientConfig:
    client: str
    client_version: str | None
    format: str
    format_revision: int
    server_url: str
    approved_origin: str
    entry_name: str
    credential_environment: str
    file_scope: str
    loopback_reachable: bool = False
    allow_remote_http: bool = False

    def __post_init__(self):
        if (not isinstance(self.client, str) or self.client not in _FORMATS or
                self.format != _FORMATS[self.client] or
                type(self.format_revision) is not int or self.format_revision != PARTICIPANT_CONFIG_REVISION or
                not isinstance(self.entry_name, str) or not _NAME.fullmatch(self.entry_name) or
                not isinstance(self.credential_environment, str) or not _ENV.fullmatch(self.credential_environment) or
                type(self.loopback_reachable) is not bool or type(self.allow_remote_http) is not bool):
            raise CoreError('VALIDATION_ERROR', 'participant_configuration')
        if self.client == 'generic':
            valid = self.client_version is None and self.file_scope == 'manual'
        else:
            valid = (isinstance(self.client_version, str) and bool(_VERSION.fullmatch(self.client_version))
                and self.file_scope in ('project', 'user', 'selected'))
        if not valid:
            raise CoreError('VALIDATION_ERROR', 'participant_configuration')
        origin, loopback = _origin(self.server_url)
        if origin != self.approved_origin or urlsplit(self.server_url).path != '/mcp':
            raise CoreError('BINDING_NOT_AUTHORIZED', 'participant_configuration')
        if loopback and not self.loopback_reachable:
            raise CoreError('WORKSPACE_UNAVAILABLE', 'participant_configuration')
        if origin.startswith('http://') and not loopback and not self.allow_remote_http:
            raise CoreError('BINDING_NOT_AUTHORIZED', 'participant_configuration')

    def entry(self) -> dict[str, Any]:
        if self.client == 'codex':
            return dict(url=self.server_url, bearer_token_env_var=self.credential_environment)
        if self.client == 'claude':
            return dict(type='http', url=self.server_url,
                headers={'Authorization': 'Bearer ${' + self.credential_environment + '}'})
        return dict(transport='streamable_http', url=self.server_url,
            authentication=dict(scheme='Bearer', reference=dict(kind='environment', name=self.credential_environment)))

    def to_dict(self) -> dict[str, Any]:
        """Non-secret host review metadata, not a portable credential export."""
        return asdict(self)


def participant_client_config(*, client: str, client_version: str | None,
        server_url: str, approved_origin: str, entry_name: str,
        credential_environment: str, file_scope: str,
        loopback_reachable: bool = False, allow_remote_http: bool = False) -> ParticipantClientConfig:
    if not isinstance(client, str) or client not in _FORMATS:
        raise CoreError('CAPABILITY_UNSUPPORTED', 'participant_configuration')
    return ParticipantClientConfig(client, client_version, _FORMATS[client],
        PARTICIPANT_CONFIG_REVISION, server_url, approved_origin, entry_name,
        credential_environment, file_scope, loopback_reachable, allow_remote_http)


def export_participant_config(config: ParticipantClientConfig) -> str:
    """Render references only. Generic output is an instruction, not installation."""
    _require_config(config)
    if config.client == 'codex':
        return (f'[mcp_servers.{config.entry_name}]\n'
            f'url = {json.dumps(config.server_url)}\n'
            f'bearer_token_env_var = {json.dumps(config.credential_environment)}\n')
    if config.client == 'claude':
        value = {'mcpServers': {config.entry_name: config.entry()}}
    else:
        value = dict(format_revision=PARTICIPANT_CONFIG_REVISION, state='manual_configuration_required',
            entry_name=config.entry_name, connection=config.entry())
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def _require_config(config):
    if type(config) is not ParticipantClientConfig:
        raise CoreError('VALIDATION_ERROR', 'participant_configuration')
    config.__post_init__()


def plan_participant_config(document: bytes | None, config: ParticipantClientConfig, *,
        previously_owned: Mapping[str, Any] | None = None) -> JsonConfigPlan | TomlConfigPlan:
    """Plan exactly one entry; ownership must come from the host's saved receipt."""
    _require_config(config)
    if config.client == 'codex':
        return _plan_codex_entry(document, entry_name=config.entry_name,
            proposed=config.entry(), fragment=export_participant_config(config),
            previously_owned=previously_owned)
    if config.client == 'claude':
        return plan_json_entry(document, section='mcpServers', entry_name=config.entry_name,
            proposed=config.entry(), previously_owned=previously_owned)
    raise CoreError('CAPABILITY_UNSUPPORTED', 'participant_configuration')


def plan_participant_removal(document: bytes | None, config: ParticipantClientConfig, *,
        previously_owned: Mapping[str, Any]) -> JsonConfigPlan | TomlConfigPlan:
    """Compensate only the owned entry; never restore an entire stale backup."""
    _require_config(config)
    if dict(previously_owned) != config.entry():
        raise CoreError('PROFILE_DRIFT', 'participant_configuration')
    if config.client == 'codex':
        return plan_codex_toml_entry_removal(document, entry_name=config.entry_name,
            previously_owned=previously_owned)
    if config.client == 'claude':
        return plan_json_entry_removal(document, section='mcpServers', entry_name=config.entry_name,
            previously_owned=previously_owned)
    raise CoreError('CAPABILITY_UNSUPPORTED', 'participant_configuration')
