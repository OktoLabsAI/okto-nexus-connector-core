// Core-owned Pi extension. Pi loads this local file; no runtime code download.
// A trusted host supplies a narrow, authenticated loopback JSONL socket.
import { createConnection } from "node:net";
const actions = [
  ["nexus_handoff_get", "handoff.get", { handoff_id: { type: "string" } }],
  ["nexus_handoff_claim", "handoff.claim", {
    handoff_id: { type: "string" }, idempotency_key: { type: "string" },
    claim_epoch: { type: "integer", minimum: 1 },
  }],
  ["nexus_handoff_complete", "handoff.complete", {
    handoff_id: { type: "string" }, claim_epoch: { type: "integer", minimum: 1 },
    result: {},
  }],
];

function required(value, name, maximum = 160) {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum ||
      /[\r\n\0]/u.test(value)) throw new Error(`invalid ${name}`);
  return value;
}

function configuration() {
  const portText = process.env.NEXUS_NATIVE_ACTION_PORT;
  const capability = process.env.NEXUS_NATIVE_CAPABILITY_REF;
  const session = process.env.NEXUS_NATIVE_SESSION_ID;
  if (!portText || !capability || !session) throw new Error("native action host unavailable");
  if (!/^[1-9][0-9]{0,4}$/u.test(portText)) throw new Error("invalid native action port");
  const port = Number(portText);
  if (port > 65535) throw new Error("invalid native action port");
  if (!capability.startsWith("native-cap:")) throw new Error("invalid native capability");
  return { port, capability: required(capability, "capability", 256),
    session: required(session, "session") };
}

function exchange(port, record, signal, uncertain) {
  return new Promise((resolve, reject) => {
    const socket = createConnection({ host: "127.0.0.1", port });
    let settled = false;
    let buffer = Buffer.alloc(0);
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", abort);
      socket.destroy();
      if (error) reject(new Error(error)); else resolve(value);
    };
    const abort = () => finish(uncertain);
    signal?.addEventListener("abort", abort, { once: true });
    socket.setTimeout(10000, () => finish(uncertain));
    socket.on("error", () => finish(uncertain));
    socket.on("close", () => finish(uncertain));
    socket.on("connect", () => {
      if (signal?.aborted) return finish(uncertain);
      socket.write(`${JSON.stringify(record)}\n`);
    });
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > 16 * 1024 + 1) return finish(uncertain);
      const end = buffer.indexOf(10);
      if (end < 0) return;
      if (end !== buffer.length - 1) return finish(uncertain);
      let reply;
      try { reply = JSON.parse(buffer.subarray(0, end).toString("utf8")); }
      catch { return finish(uncertain); }
      if (!reply || reply.ok !== true || !reply.data ||
          typeof reply.data !== "object" || Array.isArray(reply.data) ||
          ["jsonrpc", "method", "tools"].some((key) => key in reply.data)) {
        return finish(uncertain);
      }
      finish(null, reply.data);
    });
  });
}

export default function (pi) {
  for (const [name, action, properties] of actions) {
    const requiredFields = action === "handoff.get" ? ["handoff_id"] :
      action === "handoff.claim" ? ["handoff_id", "idempotency_key"] :
      ["handoff_id", "claim_epoch", "result"];
    pi.registerTool({
      name, label: name, description: `Nexus native ${action} action`,
      parameters: { type: "object", properties, required: requiredFields,
        additionalProperties: false },
      async execute(toolCallId, params, signal) {
        const { port, capability, session } = configuration();
        required(toolCallId, "operation");
        required(params.handoff_id, "handoff");
        if (action === "handoff.claim") required(params.idempotency_key, "idempotency key", 128);
        if (action === "handoff.claim" && params.claim_epoch !== undefined &&
            (!Number.isSafeInteger(params.claim_epoch) || params.claim_epoch < 1)) {
          throw new Error("invalid claim epoch");
        }
        if (action === "handoff.complete" && (!Number.isSafeInteger(params.claim_epoch) ||
            params.claim_epoch < 1)) throw new Error("invalid claim epoch");
        if (action === "handoff.complete" && (params.result === undefined ||
            (params.result && typeof params.result === "object" &&
             ["jsonrpc", "method", "params", "tools", "mcpServers"].some(
               (key) => Object.hasOwn(params.result, key))))) {
          throw new Error("invalid completion result");
        }
        const request = { action, operation_id: toolCallId, session_id: session,
          capability_ref: capability,
          handoff_id: params.handoff_id };
        if (action === "handoff.claim") {
          request.idempotency_key = params.idempotency_key;
          if (params.claim_epoch !== undefined) request.claim_epoch = params.claim_epoch;
        }
        if (action === "handoff.complete") {
          request.claim_epoch = params.claim_epoch;
          request.result = params.result;
        }
        if (Buffer.byteLength(JSON.stringify(request), "utf8") > 16 * 1024) {
          throw new Error("native action payload too large");
        }
        const uncertain = action === "handoff.get" ? "EXECUTOR_OFFLINE" : "OUTCOME_UNKNOWN";
        const data = await exchange(port, request, signal, uncertain);
        return { content: [{ type: "text", text: JSON.stringify(data) }], details: data };
      },
    });
  }
}
