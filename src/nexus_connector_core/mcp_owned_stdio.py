"""MCP SDK streams backed by Core's owned process tree, including host death."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import shutil

import anyio
from mcp.shared.session import SessionMessage
from mcp.types import JSONRPCMessage

from .models import CoreError
from .native.process import spawn_owned_process, observe_owned_process


def stop_owned(process):
    process.kill()
    process.wait(timeout=5)
    if not observe_owned_process(process)['stop_observed']:
        raise CoreError('OUTCOME_UNKNOWN', 'mcp_containment')


@asynccontextmanager
async def owned_stdio(entry, *, cwd, env, owned):
    executable = shutil.which(entry['command'], path=env.get('PATH'))
    if not executable:
        raise CoreError('BINARY_NOT_FOUND', 'mcp_preset')
    argv = [str(Path(executable).resolve()), *entry['args']]
    if Path(executable).suffix.lower() == '.cmd':
        from .discovery import resolve_windows_npm_shim
        script = resolve_windows_npm_shim(executable)
        node = Path(executable).parent / 'node.exe'
        if not node.is_file():
            node = Path(shutil.which('node', path=env.get('PATH')) or '')
        if not node.is_file():
            raise CoreError('BINARY_NOT_FOUND', 'mcp_preset')
        argv = [str(node.resolve()), str(script), *entry['args']]
    spawn = asyncio.create_task(asyncio.to_thread(spawn_owned_process, argv, cwd=cwd, env=env))
    try:
        process = await asyncio.shield(spawn)
    except BaseException:
        # Cancellation cannot abandon a process being created in a worker.
        process = await spawn
        owned.add(process)
        await asyncio.to_thread(stop_owned, process)
        owned.discard(process)
        raise
    owned.add(process)
    incoming, read = anyio.create_memory_object_stream(16)
    write, outgoing = anyio.create_memory_object_stream(16)

    async def receive():
        async with incoming:
            while True:
                line = await asyncio.to_thread(process.stdout.readline, 1024 * 1024 + 1)
                if not line:
                    return
                if not line.endswith(b'\n') or len(line) > 1024 * 1024:
                    await incoming.send(ValueError('MCP frame exceeds limit'))
                    return
                try:
                    value = SessionMessage(JSONRPCMessage.model_validate_json(line))
                except Exception:
                    value = ValueError('Invalid MCP frame')
                await incoming.send(value)

    async def send():
        async with outgoing:
            async for message in outgoing:
                payload = message.message.model_dump_json(by_alias=True, exclude_none=True).encode() + b'\n'
                if len(payload) > 1024 * 1024:
                    raise ValueError('MCP frame exceeds limit')
                await asyncio.to_thread(process.stdin.write, payload)
                await asyncio.to_thread(process.stdin.flush)

    async def drain():
        # External diagnostics may contain secrets. Drain without retaining or
        # logging them so a full stderr pipe cannot deadlock the MCP server.
        while await asyncio.to_thread(process.stderr.read, 8192):
            pass

    tasks = [asyncio.create_task(fn()) for fn in (receive, send, drain)]
    try:
        yield read, write
    finally:
        await asyncio.to_thread(stop_owned, process)
        owned.discard(process)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for stream in (incoming, read, write, outgoing):
            await stream.aclose()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
