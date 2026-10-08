// Core-owned Pi extension. Pi loads this local file; no runtime code download.
// A trusted host supplies a narrow, authenticated loopback JSONL socket.
import { createConnection } from "node:net";
const actions = [
  ["nexus_agent_list", "agent.list", {}],
  ["nexus_agent_get", "agent.get", {agent_id: {type: "string"}}],
  ["nexus_capability_list", "capability.list", {}],
  ["nexus_coordination_health", "coordination.health", {window: {type: "string", enum: ["1h", "24h", "7d"]}}],
  ["nexus_message_create", "message.create", {message: {type: "object", additionalProperties: false,
    properties: {subject: {type: "string"}, body: {type: "string"}, target: {type: "object"},
      channel_id: {type: "string"}, parent_message_id: {type: "string"},
      artifacts: {type: "array", items: {type: "string"}}}, required: ["subject", "body", "target"]}}],
  ["nexus_runtime_input_list", "runtime.input.list", {}],
  ["nexus_runtime_input_respond", "runtime.input.respond", {request: {type: "object"}}],
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
      if (error) reject(error instanceof Error ? error : new Error(error)); else resolve(value);
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
      // A correlated rejection is a known outcome, not a lost acknowledgement.
      // Preserve the host's effect/retry facts; malformed or unrelated replies
      // still take the conservative transport-uncertainty path below.
      if (reply?.ok === false && reply.operation_id === record.operation_id &&
          typeof reply.code === "string" && /^[A-Z][A-Z0-9_]{0,79}$/u.test(reply.code) &&
          typeof reply.possible_effect === "boolean" && typeof reply.retry_safe === "boolean") {
        return finish(Object.assign(new Error(`${reply.code} (possible_effect=${reply.possible_effect}, retry_safe=${reply.retry_safe})`), {
          code: reply.code, possible_effect: reply.possible_effect,
          retry_safe: reply.retry_safe, operation_id: reply.operation_id,
        }));
      }
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
  pi.registerTool({
    name: "nexus_ask_user", label: "Ask the conversation recipient",
    description: "Ask your Nexus conversation recipient a question and wait for their answer through Pi's native UI protocol. Use select for choices, confirm for a boolean, input for text, or editor for longer text.",
    parameters: {type: "object", additionalProperties: false,
      properties: {method: {type: "string", enum: ["select", "confirm", "input", "editor"]},
        title: {type: "string"}, options: {type: "array", items: {type: "string"}, minItems: 1, maxItems: 32},
        message: {type: "string"}, placeholder: {type: "string"}, prefill: {type: "string"}},
      required: ["method", "title"]},
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      required(params.title, "question", 4096);
      if (!ctx?.ui) throw new Error("Pi question UI is unavailable");
      let value;
      if (params.method === "select") {
        if (!Array.isArray(params.options) || !params.options.length || params.options.length > 32 ||
            new Set(params.options).size !== params.options.length) throw new Error("Invalid question options");
        params.options.forEach(option => required(option, "option", 4096));
        value = await ctx.ui.select(params.title, params.options, {signal});
      } else if (params.method === "confirm") {
        value = await ctx.ui.confirm(params.title, params.message ?? "", {signal});
      } else if (params.method === "input") {
        value = await ctx.ui.input(params.title, params.placeholder, {signal});
      } else if (params.method === "editor") {
        value = await ctx.ui.editor(params.title, params.prefill);
      } else throw new Error("Invalid question method");
      const data = value === undefined ? {cancelled: true} : {answer: value};
      return {content: [{type: "text", text: JSON.stringify(data)}], details: data};
    },
  });
  for (const [name, action, properties] of actions) {
    const discovery = ["agent.list", "agent.get", "capability.list", "coordination.health"].includes(action);
    const requiredFields = discovery ? (action === "agent.get" ? ["agent_id"] : []) : action === "message.create" ? ["message"] : action === "runtime.input.list" ? [] :
      action === "runtime.input.respond" ? ["request"] : action === "handoff.get" ? ["handoff_id"] :
      action === "handoff.claim" ? ["handoff_id", "idempotency_key"] :
      ["handoff_id", "claim_epoch", "result"];
    pi.registerTool({
      name, label: name, description: discovery ? ({
        "agent.list": "List agents reachable under your communication permissions, with presence and connection status. Online does not guarantee delivery.",
        "agent.get": "Read a reachable agent's profile, presence and connection status by agent_id. The target ID does not change your authenticated identity.",
        "capability.list": "List the capability catalog and owners reachable under your communication permissions.",
        "coordination.health": "Read coordination health for this session's workspace. Requires the enabled health feature and your health.read permission."
      })[action] : action === "message.create" ?
        'Send a Nexus message as your authenticated runtime agent in its workspace. Use message={subject,body,target:{strategy:"direct",agent_id:"recipient"}} or target:{strategy:"broadcast"}. Routing and message permissions still apply. Discover peers with nexus_agent_list. Sender and workspace are supplied by the session. Replaying the same tool call ID cannot create a second message. The result can require operator approval.' : action === "runtime.input.list" ?
        "List native questions addressed to you in this session's workspace. Return the native answer with nexus_runtime_input_respond." :
        action === "runtime.input.respond" ?
        "Answer a question addressed to you. Copy approval_key, expected_revision, request_hash and cas_token from the listed question into request. Add decision approve or deny and response when approving. Omit client_intent_id; the tool call supplies it. Preserve the native response contract: Codex answers={question_id:{answers:[text]}}; Claude answers={question_text:text}; Pi value=text or confirmed=boolean; MCP content={field:value}." : `Nexus native ${action} action`,
      parameters: { type: "object", properties, required: requiredFields,
        additionalProperties: false },
      async execute(toolCallId, params, signal) {
        const { port, capability, session } = configuration();
        required(toolCallId, "operation");
        if (action.startsWith("handoff.")) required(params.handoff_id, "handoff");
        if (action === "runtime.input.respond" && (!params.request || typeof params.request !== "object" ||
            Array.isArray(params.request) || Object.hasOwn(params.request, "client_intent_id"))) throw new Error("invalid question response");
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
          capability_ref: capability };
        if (action.startsWith("handoff.")) request.handoff_id = params.handoff_id;
        if (action === "agent.get") request.agent_id = required(params.agent_id, "agent");
        if (action === "coordination.health" && params.window !== undefined) request.window = params.window;
        if (action === "runtime.input.respond") request.request = params.request;
        if (action === "message.create") request.message = params.message;
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
        const uncertain = discovery || ["handoff.get", "runtime.input.list"].includes(action) ? "EXECUTOR_OFFLINE" : "OUTCOME_UNKNOWN";
        const data = await exchange(port, request, signal, uncertain);
        return { content: [{ type: "text", text: JSON.stringify(data) }], details: data };
      },
    });
  }
}
