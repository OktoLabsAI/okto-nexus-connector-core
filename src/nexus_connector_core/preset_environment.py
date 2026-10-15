"""Host-only MCP preset compilation; credentials never enter native arguments."""
import hashlib
import re
from pathlib import Path

from .models import CoreError
from .mcp_presets import validate_mcp_preset


async def compile_preset(prepared, resolver, env, *, inherit_global):
    from .environment import _check_name, _check_value
    from .mcp_inheritance import _read, codex_mcp_names
    adapter = prepared.intent.adapter_id
    preset = validate_mcp_preset(list(prepared.intent.mcp_preset))
    if adapter not in ('codex_app_server', 'claude_stream'):
        raise CoreError('CAPABILITY_UNSUPPORTED', 'mcp_preset')
    approved = set(prepared.secret_refs)
    entries, disabled = {}, set()
    known = set(codex_mcp_names(env, prepared.cwd)) if adapter == 'codex_app_server' else set()

    def protect(value, identity):
        _check_value(value)
        name = 'OKTO_MCP_' + hashlib.sha256(identity.encode()).hexdigest()[:32].upper()
        if name in env and env[name] != value:
            raise CoreError('BINDING_NOT_AUTHORIZED', 'mcp_preset')
        env[name] = value
        return name

    async def secret(reference):
        if reference not in approved:
            raise CoreError('BINDING_NOT_AUTHORIZED', 'mcp_preset')
        try:
            value = await resolver.resolve(reference)
            _check_value(value)
            if not value:
                raise ValueError()
            return value
        except Exception:
            raise CoreError('PROVIDER_AUTH_REQUIRED', 'mcp_preset',
                            message='An approved MCP credential is unavailable on this host.') from None

    if adapter == 'claude_stream' and inherit_global:
        path = (Path(env['CLAUDE_CONFIG_DIR']) / '.claude.json' if env.get('CLAUDE_CONFIG_DIR')
                else Path(env['HOME']) / '.claude.json')
        try:
            inherited = _read(path, 'mcpServers')
            overridden = {entry['name'].casefold() for entry in preset}
            for name, entry in inherited.items():
                if name.casefold() in overridden or name.lower().startswith('nexus'):
                    continue
                if not isinstance(entry, dict):
                    raise ValueError()
                native = dict(entry)
                # Native interpolation is single-pass. Expand the approved global
                # references before replacing literals with private process vars.
                def protected(value, key):
                    if not isinstance(value, str):
                        raise ValueError()
                    def expand(match):
                        key, default = match.group(1), match.group(2)
                        if key not in env and default is None:
                            raise ValueError()
                        return env.get(key, default or '')
                    value = re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}', expand, value)
                    return '${' + protect(value, 'global:' + name + ':' + key) + '}'
                for key in ('command', 'url'):
                    if key in native:
                        native[key] = protected(native[key], key)
                if 'args' in native:
                    native['args'] = [protected(v, 'args:' + str(i)) for i, v in enumerate(native['args'])]
                for key in ('env', 'headers'):
                    if key in native:
                        native[key] = {k: protected(v, key + ':' + k) for k, v in native[key].items()}
                # The factory puts the composed Claude configuration in a
                # private session file; helpers and OAuth extensions are retained
                # without exposing their literals in process arguments.
                entries[name] = native
        except (OSError, ValueError, TypeError, AttributeError):
            raise CoreError('PROFILE_DRIFT', 'mcp_preset',
                            message='The global MCP configuration cannot be safely composed with this preset.') from None
    for entry in preset:
        name = entry['name']
        collisions = {n for n in known if n.casefold() == name.casefold()}
        disabled.update(collisions)
        if not entry['enabled']:
            continue
        if adapter == 'codex_app_server' and collisions:
            # Codex recursively merges tables. Disable the old entry and use a
            # deterministic namespace, so stale transport/auth fields cannot leak.
            name = 'okto_' + name[:36] + '_' + hashlib.sha256(name.encode()).hexdigest()[:12]
            if name in known:
                raise CoreError('PROFILE_DRIFT', 'mcp_preset')
        if entry['transport'] == 'stdio':
            native = dict(command=entry['command'], args=entry['args'], env=dict(entry['env']))
            for key, reference in entry['env_refs'].items():
                _check_name(key)
                value = await secret(reference)
                if adapter == 'codex_app_server':
                    if key in env and env[key] != value:
                        raise CoreError('BINDING_NOT_AUTHORIZED', 'mcp_preset',
                                        message='Conflicting MCP environment references require distinct variable names.')
                    env[key] = value
                    native.setdefault('env_vars', []).append(key)
                else:
                    native['env'][key] = '${' + protect(value, reference) + '}'
        else:
            native = dict(url=entry['url'])
            headers = {}
            for key, value in entry.get('headers', {}).items():
                variable = protect(value, 'literal:' + name + ':header:' + key)
                headers[key] = variable if adapter == 'codex_app_server' else '${' + variable + '}'
            for key, reference in entry['header_refs'].items():
                variable = protect(await secret(reference), reference)
                headers[key] = variable if adapter == 'codex_app_server' else '${' + variable + '}'
            native['env_http_headers' if adapter == 'codex_app_server' else 'headers'] = headers
        if adapter == 'claude_stream':
            native['type'] = entry['transport']
        entries[name] = native
    return entries, tuple(sorted(disabled))
