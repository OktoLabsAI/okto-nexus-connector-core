"""Opt-in Windows campaign using installed harnesses and isolated login homes."""
import asyncio
import os
from pathlib import Path
import sys
import time

import pytest
from nexus_connector_core import ExecutionContext
from nexus_connector_core.discovery import candidate, candidate_pi_node_cli
from nexus_connector_core.environment import child_environment
from nexus_connector_core.harness_config import harness_http_template
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import LaunchIntent, OpenOperation, ShutdownPolicy, TurnOperation
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.runtime import LocalRuntimeCore


@pytest.mark.skipif(os.environ.get('OKTO_NEXUS_REAL_MCP_PRESETS') != '1' or sys.platform != 'win32',
                    reason='Installed Windows harness campaign is opt-in.')
@pytest.mark.parametrize('adapter', ['codex_app_server', 'claude_stream', 'pi_rpc'])
@pytest.mark.parametrize('inject_nexus', [True, False])
def test_installed_harness_loads_preset_without_global_configuration_changes(tmp_path, adapter, inject_nexus):
    if adapter == 'codex_app_server':
        binary = Path.home() / 'AppData/Roaming/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
        selected = candidate(adapter, binary, explicit=True)
    elif adapter == 'claude_stream':
        selected = candidate(adapter, Path.home() / '.local/bin/claude.exe', explicit=True)
    else:
        selected = candidate_pi_node_cli(Path('C:/Program Files/nodejs/node.exe'),
            Path.home() / '.pi/agent/install/releases/0.87.1/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js', explicit=True)
    home = tmp_path / 'isolated-login'
    home.mkdir()
    script = tmp_path / 'preset_server.py'
    marker = tmp_path / 'tools-discovered'
    script.write_text('''import asyncio, sys
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
server = Server("native-preset-proof")
@server.list_tools()
async def tools():
    Path(sys.argv[1]).write_text("discovered")
    return [Tool(name="preset_ping", description="A local test tool", inputSchema={"type":"object","properties":{}})]
@server.call_tool()
async def call(name, arguments):
    return [TextContent(type="text", text="pong")]
async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
asyncio.run(main())
''', encoding='utf-8')
    class Resolver:
        async def resolve(self, ref):
            assert ref == 'mcp-cap:isolated-test'
            return 'isolated-test-value'
    async def run():
        templates = () if adapter == 'pi_rpc' or not inject_nexus else (harness_http_template(adapter,
            'http://127.0.0.1:1/mcp', 'mcp-cap:isolated-test', entry_name='nexus_session',
            harness_is_local=True, loopback_reachable=True,
            approved_origins={'http://127.0.0.1:1'}, format_qualified=True),)
        async def environment(prepared):
            return await child_environment(prepared, Resolver(), provider_home=home, trusted_home=True,
                http_templates=templates, process_http=bool(templates), public_overrides={
                    'APPDATA': str(home / 'AppData/Roaming'), 'LOCALAPPDATA': str(home / 'AppData/Local')})
        journal = SQLiteJournal(tmp_path / 'journal.db')
        runtime = LocalRuntimeCore(journal, CopiedAdapterFactory(environment), candidates={adapter: selected},
                                  workspace_roots={'ws': str(tmp_path)})
        context = ExecutionContext('srv', 'exe', 'binding', 'agent', 'ws', 1, 1, 1,
            time.monotonic() + 90, frozenset({'runtime.open', 'turn.submit', 'runtime.close'}))
        try:
            launch = LaunchIntent('agent', 'ws', adapter, auth_refs=('mcp-cap:isolated-test',),
                model='anthropic/claude-haiku-4-5' if adapter == 'pi_rpc' else None,
                mcp_preset=({'name': 'toolcheck', 'transport': 'stdio', 'command': sys.executable,
                             'args': [str(script), str(marker)]},))
            prepared = await runtime.prepare(launch, context)
            await runtime.open(OpenOperation('open', 'session', 'epoch', prepared), context)
            # No provider account is exposed. The turn will fail authentication;
            # the assertion independently proves native MCP tool discovery.
            await runtime.submit(TurnOperation('turn', 'session', 'Do not call tools. Reply OK.'), context)
            async with asyncio.timeout(35):
                while not marker.exists():
                    await asyncio.sleep(.1)
            assert marker.read_text() == 'discovered'
        finally:
            await runtime.shutdown(ShutdownPolicy(2, 2))
            journal.close()
    asyncio.run(run())
