"""Validated per-session MCP definitions. No credential resolution or I/O.

Presets are public configuration. Literals are persisted as configuration;
host-local references are preferred for secrets. Rendering requires authorization.
"""
from copy import deepcopy
import hashlib
import json
import re
from urllib.parse import urlsplit

from .models import CoreError

_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z', re.ASCII)
_ENV = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}\Z', re.ASCII)
_HEADER = re.compile(r'[A-Za-z0-9!#$%&\'*+.^_`|~-]{1,128}\Z', re.ASCII)


def _invalid(message='Invalid MCP preset.'):
    raise CoreError('VALIDATION_ERROR', 'mcp_preset', message=message)


def _text(value, limit=4096):
    return (type(value) is str and len(value) <= limit and
            not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _reference(value):
    return (_text(value, 256) and value.startswith(('vault:', 'provider:'))
            and bool(value.partition(':')[2].strip()))


def validate_mcp_preset(value):
    if type(value) is not list or len(value) > 32:
        _invalid()
    names = set()
    result = []
    for source in value:
        if type(source) is not dict:
            _invalid()
        entry = deepcopy(source)
        name = entry.get('name')
        if (type(name) is not str or not _NAME.fullmatch(name) or name.lower().startswith('nexus')
                or name.casefold() in names):
            _invalid('MCP names must be unique; the Nexus namespace is reserved.')
        names.add(name.casefold())
        if type(entry.get('enabled', True)) is not bool:
            _invalid()
        entry.setdefault('enabled', True)
        transport = entry.get('transport')
        common = {'name', 'enabled', 'transport'}
        fields = ({'command', 'args', 'env', 'env_refs'} if transport == 'stdio'
                  else {'url', 'headers', 'header_refs'} if transport == 'http' else None)
        if fields is None or set(entry) - common - fields:
            _invalid()
        if transport == 'stdio':
            if not _text(entry.get('command')) or not entry['command'].strip():
                _invalid()
            args = entry.setdefault('args', [])
            if type(args) is not list or len(args) > 128 or any(not _text(a) for a in args):
                _invalid()
            env = entry.setdefault('env', {})
            refs = entry.setdefault('env_refs', {})
            for mapping, references in ((env, False), (refs, True)):
                if type(mapping) is not dict or len(mapping) > 64:
                    _invalid()
                for key, item in mapping.items():
                    if (type(key) is not str or not _ENV.fullmatch(key) or key.upper().startswith('NEXUS_')
                            or not (_reference(item) if references else _text(item))):
                        _invalid()
            if set(env) & set(refs):
                _invalid('An environment variable cannot have both a literal and a secret reference.')
        else:
            url = entry.get('url')
            if not _text(url) or not url or '\\' in url or any(c.isspace() for c in url):
                _invalid()
            try:
                parts = urlsplit(url)
                port = parts.port
                valid = (parts.scheme in ('http', 'https') and parts.hostname and not parts.username
                         and not parts.password and not parts.fragment and not parts.query
                         and port != 0)
            except ValueError:
                valid = False
            if not valid:
                _invalid('MCP URL must be HTTP(S), without credentials, query or fragment.')
            refs = entry.setdefault('header_refs', {})
            headers = entry.get('headers', {})
            if type(refs) is not dict or type(headers) is not dict or len(refs) + len(headers) > 32:
                _invalid()
            keys = [*headers, *refs]
            if len({k.casefold() for k in keys if type(k) is str}) != len(keys):
                _invalid()
            for mapping, references in ((headers, False), (refs, True)):
                for key, item in mapping.items():
                    if type(key) is not str or not _HEADER.fullmatch(key) or not (_reference(item) if references else _text(item)):
                        _invalid()
        result.append(entry)
    if len(json.dumps(result, ensure_ascii=False).encode()) > 32768:
        _invalid('MCP preset exceeds 32 KiB.')
    return result


def mcp_preset_digest(value):
    normalized = validate_mcp_preset(value)
    return 'sha256:' + hashlib.sha256(json.dumps(normalized, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def compose_mcp_preset(inherited, preset, nexus_entries, *, inherit_global):
    """Whole-entry replacement; disabled preset entries remove inherited names."""
    if type(inherited) is not dict or type(nexus_entries) is not dict or type(inherit_global) is not bool:
        _invalid()
    result = deepcopy(inherited) if inherit_global else {}
    for entry in validate_mcp_preset(preset):
        name = entry['name']
        # Never leave a case-variant duplicate around on case-insensitive hosts.
        for existing in tuple(result):
            if existing.casefold() == name.casefold():
                del result[existing]
        if entry['enabled']:
            result[name] = entry
    for name, entry in nexus_entries.items():
        for existing in tuple(result):
            if existing.casefold() == name.casefold():
                del result[existing]
        result[name] = deepcopy(entry)
    return result


def render_mcp_preset(adapter_id, preset, resolve_secret):
    """Translate approved definitions in host memory; never persist resolved values.

    Pi requires a tool bridge and must not silently pretend it loads native MCPs.
    """
    entries = validate_mcp_preset(preset)
    if adapter_id not in ('codex_app_server', 'claude_stream'):
        raise CoreError('CAPABILITY_UNSUPPORTED', 'mcp_preset')
    result = {}
    for entry in entries:
        if not entry['enabled']:
            continue
        def resolve(reference):
            value = resolve_secret(reference)
            if not _text(value, 16384) or not value:
                raise CoreError('PROVIDER_AUTH_REQUIRED', 'mcp_preset', message='MCP secret is unavailable on this host.')
            return value
        if entry['transport'] == 'stdio':
            native = {'command': entry['command'], 'args': list(entry['args']),
                      'env': {**entry['env'], **{k: resolve(v) for k, v in entry['env_refs'].items()}}}
            if adapter_id == 'claude_stream':
                native['type'] = 'stdio'
        else:
            native = {'url': entry['url']}
            native['http_headers' if adapter_id == 'codex_app_server' else 'headers'] = {
                **entry.get('headers', {}), **{k: resolve(v) for k, v in entry['header_refs'].items()}}
            if adapter_id == 'claude_stream':
                native['type'] = 'http'
        result[entry['name']] = native
    return result
