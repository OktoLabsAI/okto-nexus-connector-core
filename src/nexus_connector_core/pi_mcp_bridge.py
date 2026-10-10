"""Session-owned MCP client for Pi's injected external tools.

The loopback token grants access only to the preset's tool snapshot. Nexus
tools retain their separate capability transport and permission checks.
"""
import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
import hashlib
import hmac
import json
import os
import secrets

from .models import CoreError
from .mcp_presets import validate_mcp_preset

MAX_FRAME = 1024 * 1024


class PiMCPBridge:
    def __init__(self, preset, resolver, approved_refs, *, cwd, environment):
        self._preset = validate_mcp_preset(list(preset))
        self._resolver = resolver
        self._approved = set(approved_refs)
        self._cwd = cwd
        from .environment import _ESSENTIALS
        self._environment = {k: v for k, v in (dict(os.environ) | dict(environment)).items() if k.upper() in _ESSENTIALS}
        self._token = secrets.token_urlsafe(32)
        self._stop = asyncio.Event()
        self._task = None
        self._clients = set()
        self._tools = {}
        self._metadata = []
        self._owned = set()
        self.port = None

    def __repr__(self):
        return 'PiMCPBridge(<protected>)'

    async def _secret(self, reference):
        from .environment import _check_value
        if reference not in self._approved:
            raise CoreError('BINDING_NOT_AUTHORIZED', 'mcp_preset')
        try:
            value = await self._resolver.resolve(reference)
            _check_value(value)
            if not value:
                raise ValueError()
            return value
        except Exception:
            raise CoreError('PROVIDER_AUTH_REQUIRED', 'mcp_preset') from None

    async def start(self):
        if self._task is not None:
            raise RuntimeError('A preset bridge is single-use')
        ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run(ready))
        try:
            await asyncio.wait_for(asyncio.shield(ready), 30)
        except BaseException:
            await self.close()
            raise CoreError('MCP_STARTUP_FAILED', 'mcp_preset', retry_safe=True) from None
        return {'OKTO_PRESET_MCP_PORT': str(self.port), 'OKTO_PRESET_MCP_TOKEN': self._token}

    async def _run(self, ready):
        # The SDK uses AnyIO cancel scopes. Enter and exit every client in this
        # one owner task, never from a request handler or native adapter thread.
        try:
            from mcp import ClientSession
            from .mcp_owned_stdio import owned_stdio
            from mcp.client.streamable_http import streamablehttp_client
            async with AsyncExitStack() as stack:
                for entry in self._preset:
                    if not entry['enabled']:
                        continue
                    if entry['transport'] == 'stdio':
                        env = dict(self._environment) | entry['env']
                        for key, ref in entry['env_refs'].items():
                            from .environment import _check_name
                            _check_name(key)
                            env[key] = await self._secret(ref)
                        streams = await stack.enter_async_context(owned_stdio(entry, cwd=self._cwd, env=env, owned=self._owned))
                    else:
                        headers = {key: await self._secret(ref) for key, ref in entry['header_refs'].items()}
                        streams = await stack.enter_async_context(streamablehttp_client(entry['url'], headers=headers, timeout=15))
                    client = await stack.enter_async_context(ClientSession(streams[0], streams[1], read_timeout_seconds=timedelta(seconds=30)))
                    await client.initialize()
                    cursor = None
                    seen = set()
                    while True:
                        result = await client.list_tools(cursor=cursor)
                        for tool in result.tools:
                            name = 'mcp_' + entry['name'][:20] + '_' + hashlib.sha256((entry['name'] + ':' + tool.name).encode()).hexdigest()[:20]
                            if name in self._tools or len(self._tools) >= 256:
                                raise ValueError('Invalid tool snapshot')
                            self._tools[name] = (client, tool.name)
                            self._metadata.append(dict(name=name, label=entry['name'] + ': ' + tool.name,
                                description=(tool.description or '')[:8192], parameters=tool.inputSchema))
                        cursor = result.nextCursor
                        if not cursor:
                            break
                        if cursor in seen:
                            raise ValueError('Repeated MCP cursor')
                        seen.add(cursor)
                if len(json.dumps(self._metadata).encode()) > MAX_FRAME - 1024:
                    raise ValueError('Tool snapshot exceeds limit')
                server = await asyncio.start_server(self._accept, '127.0.0.1', 0, limit=MAX_FRAME)
                async with server:
                    self.port = server.sockets[0].getsockname()[1]
                    ready.set_result(None)
                    try:
                        await self._stop.wait()
                    finally:
                        server.close()
                        for task in tuple(self._clients):
                            task.cancel()
                        if self._clients:
                            await asyncio.gather(*tuple(self._clients), return_exceptions=True)
        except BaseException:
            if not ready.done():
                ready.set_exception(CoreError('MCP_STARTUP_FAILED', 'mcp_preset', retry_safe=True))
        finally:
            self._tools.clear()
            self._metadata.clear()

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self._clients.add(task)
        try:
            if len(self._clients) > 16:
                return
            raw = await asyncio.wait_for(reader.readline(), 5)
            if not raw.endswith(b'\n') or len(raw) > MAX_FRAME:
                return
            request = json.loads(raw)
            token = request.get('token')
            if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
                return
            if request.get('method') == 'list':
                response = {'tools': self._metadata}
            elif request.get('method') == 'call' and request.get('name') in self._tools:
                if type(request.get('arguments')) is not dict:
                    raise ValueError()
                client, name = self._tools[request['name']]
                result = await client.call_tool(name, request['arguments'], read_timeout_seconds=timedelta(seconds=60))
                response = result.model_dump(mode='json', exclude_none=True)
            else:
                raise ValueError()
            payload = json.dumps(response, ensure_ascii=False).encode() + b'\n'
            if len(payload) > MAX_FRAME:
                raise ValueError()
            writer.write(payload)
            await writer.drain()
        except Exception:
            writer.write(b'{"isError":true,"content":[{"type":"text","text":"External MCP request failed. Do not retry a potentially effective call automatically."}]}\n')
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            finally:
                self._clients.discard(task)

    async def close(self):
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 5)
            except asyncio.TimeoutError:
                from .mcp_owned_stdio import stop_owned
                for process in tuple(self._owned):
                    await asyncio.to_thread(stop_owned, process)
                    self._owned.discard(process)
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
        from .mcp_owned_stdio import stop_owned
        for process in tuple(self._owned):
            await asyncio.to_thread(stop_owned, process)
            self._owned.discard(process)
