"""Passive Windows package layouts; no shell or JavaScript is interpreted."""
import json
import os
from pathlib import Path
import re

from .discovery_control import check_discovery_cancelled


def path_directories(path_env):
    cwd = Path.cwd().resolve()
    seen = set()
    for entry in path_env.split(os.pathsep):
        check_discovery_cancelled()
        path = Path(entry)
        if not entry or not path.is_absolute():
            continue
        try:
            path = path.resolve(strict=True)
        except OSError:
            continue
        if path == cwd or path in seen or not path.is_dir():
            continue
        seen.add(path)
        yield path


def _text(path, limit=65536):
    check_discovery_cancelled()
    with path.open('r', encoding='utf-8') as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError('Layout metadata exceeds the passive read limit.')
    return value


def _package(path, name):
    try:
        value = json.loads(_text(path / 'package.json'))
        return isinstance(value, dict) and value.get('name') == name
    except (OSError, ValueError):
        return False


def windows_layout_targets(adapter_id, directories):
    """Yield fixed installed payloads, not the command a mutable shim might run.

    Every target still requires Core identity and explicit local trust selection.
    Multiple Node installations remain separate selectable Pi pairs.
    """
    if os.name != 'nt':
        return
    nodes = [directory / 'node.exe' for directory in directories
             if (directory / 'node.exe').is_file()]
    for directory in directories:
        check_discovery_cancelled()
        if adapter_id == 'codex_app_server':
            package = directory / 'node_modules' / '@openai' / 'codex'
            if not _package(package, '@openai/codex'):
                continue
            for arch, triple in (('x64', 'x86_64-pc-windows-msvc'),
                                 ('arm64', 'aarch64-pc-windows-msvc')):
                name = '@openai/codex-win32-' + arch
                for root in (package / 'node_modules' / name,
                             directory / 'node_modules' / name):
                    # npm platform packages may be aliases whose own manifest
                    # retains @openai/codex as its name.
                    if _package(root, name) or _package(root, '@openai/codex'):
                        for folder in ('bin', 'codex'):
                            yield root / 'vendor' / triple / folder / 'codex.exe', None
                # Older npm releases bundled the native payload directly.
                yield package / 'vendor' / triple / 'codex' / 'codex.exe', None
        elif adapter_id == 'pi_rpc':
            packages = [directory / 'node_modules' / '@earendil-works' / 'pi-coding-agent']
            # The managed installer places bin beside install/current-version.
            install = directory.parent / 'install'
            if directory.name.lower() == 'bin' and (directory / 'pi-launcher.js').is_file():
                try:
                    version = _text(install / 'current-version', 160).strip()
                    if version not in ('.', '..') and re.fullmatch(r'[0-9A-Za-z._+-]+', version):
                        packages.append(install / 'releases' / version / 'node_modules' /
                                        '@earendil-works' / 'pi-coding-agent')
                except (OSError, ValueError):
                    pass
            for package in packages:
                if _package(package, '@earendil-works/pi-coding-agent'):
                    script = package / 'dist' / 'bundle' / 'cli.js'
                    for node in nodes:
                        yield node, script
