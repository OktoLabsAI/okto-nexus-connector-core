// External preset tools use their own session token. Nexus capabilities are separate.
import { createConnection } from 'node:net';

function exchange(request, signal) {
  const port = Number(process.env.OKTO_PRESET_MCP_PORT);
  const token = process.env.OKTO_PRESET_MCP_TOKEN;
  if (!Number.isInteger(port) || port < 1 || port > 65535 || !token) throw new Error('MCP preset bridge unavailable');
  return new Promise((resolve, reject) => {
    const socket = createConnection({host: '127.0.0.1', port});
    let buffer = Buffer.alloc(0), done = false;
    const finish = (error, value) => {
      if (done) return;
      done = true; signal?.removeEventListener('abort', abort); socket.destroy();
      error ? reject(new Error(error)) : resolve(value);
    };
    const abort = () => finish('MCP call cancelled; side effects may already have occurred.');
    signal?.addEventListener('abort', abort, {once: true});
    socket.setTimeout(65000, () => finish('MCP call timed out; do not retry automatically.'));
    socket.on('error', () => finish('MCP bridge unavailable.'));
    socket.on('close', () => finish('MCP response was lost; do not retry automatically.'));
    socket.on('connect', () => {
      if (signal?.aborted) return abort();
      socket.write(JSON.stringify({...request, token}) + '\n');
    });
    socket.on('data', chunk => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > 1024 * 1024) return finish('MCP response exceeds limit.');
      const end = buffer.indexOf(10);
      if (end < 0) return;
      try {finish(null, JSON.parse(buffer.subarray(0, end).toString('utf8')));}
      catch {finish('Invalid MCP response.');}
    });
  });
}

export default async function (pi) {
  const snapshot = await exchange({method: 'list'});
  if (!Array.isArray(snapshot.tools)) throw new Error('MCP preset discovery failed');
  for (const tool of snapshot.tools) {
    pi.registerTool({...tool, async execute(_id, args, signal) {
      const result = await exchange({method: 'call', name: tool.name, arguments: args}, signal);
      return {content: (result.content || []).filter(item => item.type === 'text' || item.type === 'image'),
        details: {isError: result.isError === true, structuredContent: result.structuredContent}};
    }});
  }
}
