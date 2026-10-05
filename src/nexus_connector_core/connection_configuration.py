"""Portable connection preferences; never credentials or execution authority."""
import json

from .harness_configuration import validate_harness_configuration, discover_harness_configuration
from .models import CoreError
from .automation import DEFAULT_RUNTIME_AUTOMATION

CONNECTION_CONFIGURATION_FORMAT = 'okto-nexus-connection'


def parse_connection_configuration(value):
    if isinstance(value, str):
        if len(value.encode('utf-8')) > 65536:
            raise CoreError('VALIDATION_ERROR', 'connection_configuration')
        value = json.loads(value)
    fields = {'format','version','adapter_id','execution_location','runtime_enabled','session_policy',
              'workspace_root','workspace_label','provider_home','secret_bindings','alias',
              'harness_settings','automatic_reply','tool_access','authorization'}
    if not isinstance(value, dict) or set(value) != fields or value['format'] != CONNECTION_CONFIGURATION_FORMAT or type(value['version']) is not int or value['version'] != 1:
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    if (value['execution_location'] not in ('local','remote','all') or
            (value['runtime_enabled'] is not None and type(value['runtime_enabled']) is not bool) or type(value['automatic_reply']) is not bool or
            value['session_policy'] not in ('shared','per_sender','per_sender_session',None) or value['tool_access'] not in ('ask','always_allow')):
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    for name in ('workspace_root','workspace_label','alias','adapter_id'):
        if type(value[name]) is not str or len(value[name]) > 4096 or '\x00' in value[name]:
            raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    home = value['provider_home']
    if home is not None and (type(home) is not str or len(home) > 4096 or '\x00' in home):
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    limits = value['authorization']
    if not isinstance(limits, dict) or set(limits) != {'minutes','actions'}:
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    for key, maximum in [('minutes',1440),('actions',1000)]:
        if limits[key] is not None and (type(limits[key]) is not int or not 1 <= limits[key] <= maximum):
            raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    import re
    refs = value['secret_bindings']
    if not isinstance(refs, dict) or len(refs) > 64 or any(
            type(k) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', k) or
            type(v) is not str or not re.fullmatch(r'(?:provider|vault):[^\s\x00]{1,240}',v) or
            any(prefix in v for prefix in ('nxs_','nxsept_','nxc4_','nxt4_')) for k,v in refs.items()):
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    if value['adapter_id']:
        validate_harness_configuration(discover_harness_configuration(value['adapter_id']), value['harness_settings'])
    elif value['runtime_enabled'] and value['execution_location'] != 'remote' or value['harness_settings']:
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    # Compatibility field: active runtimes always receive eligible messages.
    return {**json.loads(json.dumps(value)), 'automatic_reply': DEFAULT_RUNTIME_AUTOMATION.automatic_messages}


def export_connection_configuration(value):
    return json.dumps(parse_portable_connection_configuration(value), indent=2, ensure_ascii=False) + '\n'


DESTINATION_FIELDS = {'execution_location', 'workspace_root', 'workspace_label', 'provider_home', 'secret_bindings'}
DESTINATION_DEFAULTS = dict(execution_location='local', workspace_root='', workspace_label='',
                            provider_home=None, secret_bindings={})


def parse_portable_connection_configuration(value):
    """Version 2 is a template, never a machine selection or identity.

    Legacy version 1 files are accepted only after discarding destination fields.
    The complete version 1 shape remains the internal Server setup contract.
    """
    if isinstance(value, str):
        if len(value.encode('utf-8')) > 65536:
            raise CoreError('VALIDATION_ERROR', 'connection_configuration')
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError('Duplicate configuration field')
                result[key] = item
            return result
        value = json.loads(value, object_pairs_hook=unique)
    if not isinstance(value, dict) or type(value.get('version')) is not int:
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    if value['version'] == 1:
        complete = parse_connection_configuration(value)
    elif value['version'] == 2 and not DESTINATION_FIELDS.intersection(value):
        complete = parse_connection_configuration({**value, **DESTINATION_DEFAULTS, 'version': 1})
    else:
        raise CoreError('VALIDATION_ERROR', 'connection_configuration')
    return {**{key: item for key, item in complete.items() if key not in DESTINATION_FIELDS}, 'version': 2}


def materialize_connection_configuration(value, *, execution_location='local', workspace_root='',
                                         workspace_label='', provider_home=None, secret_bindings=None):
    """Combine a template with explicitly supplied destination-host choices."""
    portable = parse_portable_connection_configuration(value)
    return parse_connection_configuration({**portable, 'version': 1,
        'execution_location': execution_location, 'workspace_root': workspace_root,
        'workspace_label': workspace_label, 'provider_home': provider_home,
        'secret_bindings': secret_bindings or {}})
