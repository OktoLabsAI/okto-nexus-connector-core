"""Host-local references needed by native MCP configuration loading.

No configuration or credential is sent to the Server or included in process
arguments. Only variables named by the approved global MCP definitions are read.
The native harness remains responsible for config precedence, OAuth and startup.
"""
import json
import os
from pathlib import Path
import re
import tomllib

from .models import CoreError


def _read(path, section):
    if not path.exists():
        return {}
    with path.open('rb') as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError()
    parsed = tomllib.loads(raw.decode('utf-8-sig')) if section == 'mcp_servers' else json.loads(raw)
    entries = parsed.get(section, {})
    if not isinstance(entries, dict):
        raise ValueError()
    return entries


def codex_mcp_names(env, cwd):
    """Names only, to override Codex's recursive table merge when opt-out is set."""
    paths = []
    if env.get('CODEX_HOME'):
        paths.append(Path(env['CODEX_HOME']) / 'config.toml')
    # Do not invent overrides for ancestor configs: Codex may not load an
    # untrusted project, and an enabled-only table lacks a valid transport.
    # This option controls the approved global home, not project trust.
    try:
        return tuple(sorted({name for path in paths for name in _read(path, 'mcp_servers')}))
    except (OSError, ValueError, TypeError, AttributeError):
        raise CoreError('PROFILE_DRIFT', 'mcp_client_configuration',
                        message='The harness MCP configuration could not be read.') from None


def global_mcp_environment(adapter_id, env):
    if adapter_id == 'codex_app_server':
        path = Path(env['CODEX_HOME']) / 'config.toml'
        section = 'mcp_servers'
    elif adapter_id == 'claude_stream':
        path = (Path(env['CLAUDE_CONFIG_DIR']) / '.claude.json' if env.get('CLAUDE_CONFIG_DIR')
                else Path(env['HOME']) / '.claude.json')
        section = 'mcpServers'
    else:
        raise CoreError('CAPABILITY_UNSUPPORTED', 'mcp_client_configuration')
    try:
        entries = _read(path, section)
        names = set()
        for entry in entries.values():
            if not isinstance(entry, dict):
                raise ValueError()
            if entry.get('enabled') is False:
                continue
            if section == 'mcp_servers':
                variables = entry.get('env_vars', [])
                headers = entry.get('env_http_headers', {})
                if not isinstance(variables, list) or not isinstance(headers, dict):
                    raise ValueError()
                names.update(variables)
                names.update(headers.values())
                if entry.get('bearer_token_env_var'):
                    names.add(entry['bearer_token_env_var'])
            else:
                names.update(re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}',
                                        json.dumps(entry)))
        # Do not broaden the normal child environment or forward Nexus access.
        from .environment import _check_name, _check_value
        values = {}
        for name in names:
            if not isinstance(name, str):
                raise ValueError()
            try:
                _check_name(name)
                value = os.environ.get(name)
                if value is None:
                    continue
                _check_value(value)
                if any(prefix in value for prefix in ('nxc4_', 'nxt4_')):
                    continue
            except CoreError:
                continue
            values[name] = value
        return values
    except (OSError, ValueError, TypeError, AttributeError):
        raise CoreError('PROFILE_DRIFT', 'mcp_client_configuration',
                        message='The global harness MCP configuration could not be read.') from None
