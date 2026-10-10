import asyncio
import json
import sys
import os
from pathlib import Path
import subprocess
import time

import pytest

from nexus_connector_core.pi_mcp_bridge import PiMCPBridge
from nexus_connector_core.models import CoreError


class Resolver:
    async def resolve(self, reference):
        assert reference == 'vault:example'
        return 'protected-server-credential'


def preset(tmp_path):
    script = tmp_path / 'server.py'
    script.write_text('''import os
from mcp.server.fastmcp import FastMCP
server = FastMCP("preset-test")
@server.tool()
def echo(text: str) -> dict:
    return {"text": text, "credential_present": os.environ.get("EXAMPLE_TOKEN") == "protected-server-credential",
            "nexus_credential_present": any(k.startswith("NEXUS_") for k in os.environ)}
server.run(transport="stdio")
''', encoding='utf-8')
    return [dict(name='example', transport='stdio', command=sys.executable, args=[str(script)],
                 env_refs={'EXAMPLE_TOKEN': 'vault:example'})]


async def exchange(port, token, **request):
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    writer.write(json.dumps(dict(token=token, **request)).encode() + b'\n')
    await writer.drain()
    response = await asyncio.wait_for(reader.readline(), 5)
    writer.close()
    await writer.wait_closed()
    return json.loads(response) if response else None


def test_real_stdio_discovery_call_authentication_and_cleanup(tmp_path):
    async def run():
        bridge = PiMCPBridge(preset(tmp_path), Resolver(), ('vault:example',), cwd=str(tmp_path), environment={})
        config = await bridge.start()
        port, token = bridge.port, config['OKTO_PRESET_MCP_TOKEN']
        try:
            assert await exchange(port, 'wrong', method='list') is None
            tools = (await exchange(port, token, method='list'))['tools']
            assert len(tools) == 1 and tools[0]['name'].startswith('mcp_example_')
            result = await exchange(port, token, method='call', name=tools[0]['name'], arguments={'text': 'hello'})
            assert result.get('isError') is not True
            text = json.loads(next(c['text'] for c in result['content'] if c['type'] == 'text'))
            assert text == {'text': 'hello', 'credential_present': True, 'nexus_credential_present': False}
            assert 'protected-server-credential' not in repr(bridge)
            denied = await exchange(port, token, method='call', name='nexus_agent_list', arguments={})
            assert denied['isError'] is True
        finally:
            await bridge.close()
        with pytest.raises(OSError):
            await asyncio.open_connection('127.0.0.1', port)
        assert bridge._task.done() and not bridge._clients and not bridge._tools
    asyncio.run(run())


def test_bridge_rejects_unapproved_secret_and_closes_startup(tmp_path):
    async def run():
        bridge = PiMCPBridge(preset(tmp_path), Resolver(), (), cwd=str(tmp_path), environment={})
        with pytest.raises(CoreError):
            await bridge.start()
        assert bridge._task.done() and bridge.port is None
    asyncio.run(run())


def test_real_http_discovery_call_and_protected_header(tmp_path):
    import socket
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from starlette.responses import Response
    from starlette.middleware.base import BaseHTTPMiddleware
    async def run():
        server = FastMCP('http-preset', stateless_http=True, json_response=True)
        @server.tool()
        def echo(text: str) -> str:
            return text
        app = server.streamable_http_app()
        seen = []
        async def authorize(request, call_next):
            seen.append(request.headers.get('authorization'))
            if seen[-1] != 'protected-server-credential':
                return Response(status_code=401)
            return await call_next(request)
        app.add_middleware(BaseHTTPMiddleware, dispatch=authorize)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        port = sock.getsockname()[1]
        host = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        serving = asyncio.create_task(host.serve(sockets=[sock]))
        bridge = PiMCPBridge([dict(name='http', transport='http', url=f'http://127.0.0.1:{port}/mcp',
            header_refs={'Authorization': 'vault:example'})], Resolver(), ('vault:example',),
            cwd=str(tmp_path), environment={})
        try:
            async with asyncio.timeout(5):
                while not host.started:
                    await asyncio.sleep(.01)
            config = await bridge.start()
            token = config['OKTO_PRESET_MCP_TOKEN']
            tools = (await exchange(bridge.port, token, method='list'))['tools']
            response = await exchange(bridge.port, token, method='call', name=tools[0]['name'], arguments={'text': 'HTTP works'})
            assert any(c.get('text') == 'HTTP works' for c in response['content'])
            assert seen and all(value == 'protected-server-credential' for value in seen)
            assert 'protected-server-credential' not in json.dumps(tools)
        finally:
            await bridge.close()
            host.should_exit = True
            await asyncio.wait_for(serving, 5)
            sock.close()
    asyncio.run(run())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows kill-on-close process ownership campaign')
def test_stdio_server_dies_when_bridge_host_is_killed(tmp_path):
    import ctypes
    from ctypes import wintypes
    definition = preset(tmp_path)[0]
    source = tmp_path / 'host.py'
    ready = tmp_path / 'ready.json'
    source.write_text('''import asyncio, json, sys
from pathlib import Path
from nexus_connector_core.pi_mcp_bridge import PiMCPBridge
class Resolver:
    async def resolve(self, ref): return "protected-server-credential"
async def main():
    bridge = PiMCPBridge(json.loads(sys.argv[1]), Resolver(), ("vault:example",), cwd=sys.argv[2], environment={})
    await bridge.start()
    Path(sys.argv[3]).write_text(json.dumps([p.pid for p in bridge._owned]))
    await asyncio.Event().wait()
asyncio.run(main())
''', encoding='utf-8')
    import nexus_connector_core
    env = dict(os.environ, PYTHONPATH=str(Path(nexus_connector_core.__file__).parents[1]))
    host = subprocess.Popen([sys.executable, str(source), json.dumps([definition]), str(tmp_path), str(ready)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists():
            assert host.poll() is None, 'Bridge host exited before readiness'
            assert time.monotonic() < deadline
            time.sleep(.05)
        pids = json.loads(ready.read_text())
        assert len(pids) == 1
        handle = kernel.OpenProcess(0x100000, False, pids[0])
        assert handle and kernel.WaitForSingleObject(handle, 0) == 258
        host.kill()
        host.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle, 10000) == 0, 'MCP process survived its owning host'
    finally:
        if host.poll() is None:
            host.kill()
            host.wait(timeout=5)
        host.stderr.close()
        if handle:
            kernel.CloseHandle(handle)
