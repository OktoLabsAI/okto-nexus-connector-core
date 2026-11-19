import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";

const RUN = /^prun_[a-f0-9]{32}$/;
const CONTROL = /^[A-Za-z0-9_.:-]{1,160}$/;
const MAX_PENDING = 50;

/** Guard the native queue after Pi's asynchronous input extension handlers. */
export function fenceHostedRpcSteer(owner, writeProtocol) {
  const session = owner.session;
  const runPrompt = session._runAgentPrompt.bind(session);
  const steer = session.steer.bind(session);
  const queueSteer = session._queueSteer.bind(session);
  const nativeSteer = session.agent.steer.bind(session.agent);
  const emit = session._emit.bind(session);
  const steering = new AsyncLocalStorage();
  let active;

  function check(run) {
    const signal = session.agent.signal;
    if (!run || active !== run || owner.session !== session || !session.isStreaming || !signal || signal.aborted) {
      throw new Error("The Pi run selected by the steering command has ended.");
    }
  }

  function fact(run, operation, stage) {
    writeProtocol(JSON.stringify({ type: "nexus_pi_steer", run_id: run.id, operation_id: operation, stage }) + "\n");
  }

  function retire(run) {
    // A scoped message still in the native queue belongs only to this run.
    // Keep other messages and their order, including equal-text entries.
    const queue = session.agent.steeringQueue;
    queue.messages = queue.messages.filter((message) => {
      const operation = run.pending.get(message);
      if (operation === undefined) return true;
      const preview = session._steeringMessages;
      const index = preview.indexOf(message.content[0].text);
      if (index >= 0) preview.splice(index, 1);
      fact(run, operation, "discarded");
      run.pending.delete(message);
      return false;
    });
    // An entry that left the queue without an observed message_start has
    // no consumption proof, so emit neither consumed nor discarded for it.
    run.pending.clear();
  }

  session._runAgentPrompt = async (...args) => {
    const run = { id: "prun_" + randomUUID().replaceAll("-", ""), pending: new Map() };
    active = run;
    try {
      return await runPrompt(...args);
    } finally {
      if (active === run) {
        if (run.pending.size) retire(run);
        active = undefined;
      }
    }
  };

  session.steer = async (text, images, options) => {
    if (options?.source !== "rpc") return steer(text, images, options);
    const run = active;
    check(run);
    if (typeof text === "string") return steering.run({ run }, () => steer(text, images, options));
    if (!text || Object.keys(text).length !== 4 || text.kind !== "nexus_hosted_steer" ||
        typeof text.run_id !== "string" || !RUN.test(text.run_id) || text.run_id !== run.id ||
        typeof text.operation_id !== "string" || !CONTROL.test(text.operation_id) ||
        typeof text.text !== "string" || !text.text) {
      throw new Error("The hosted Pi steering target is stale or invalid.");
    }
    return steering.run({ run, operation: text.operation_id }, () => steer(text.text, images, options));
  };

  session._queueSteer = (text, images) => {
    const scope = steering.getStore();
    if (scope) {
      check(scope.run);
      if (scope.operation && scope.run.pending.size >= MAX_PENDING) throw new Error("The hosted Pi steering queue is full.");
    }
    return queueSteer(text, images);
  };

  session.agent.steer = (message) => {
    const scope = steering.getStore();
    if (!scope?.operation) return nativeSteer(message);
    check(scope.run);
    nativeSteer(message);
    scope.run.pending.set(message, scope.operation);
    fact(scope.run, scope.operation, "queued");
  };

  session._emit = (event) => {
    const run = active;
    if (!run) return emit(event);
    if (event.type === "agent_start") return emit({ ...event, hosted_pi_run_id: run.id });
    if (event.type === "message_start" && run.pending.has(event.message)) {
      fact(run, run.pending.get(event.message), "consumed");
      run.pending.delete(event.message);
    } else if (event.type === "agent_settled") {
      if (run.pending.size) retire(run);
      return emit({ ...event, hosted_pi_run_id: run.id });
    }
    return emit(event);
  };

  return (onLine) => (line) => {
    // The reviewed RPC handler calls session.abort() in this same stack,
    // before its first await. Reject here before it can invoke any abort.
    let frame;
    try { frame = JSON.parse(line); } catch { return onLine(line); }
    if (frame?.type !== "abort" || !Object.hasOwn(frame, "nexus_expected_run_id")) return onLine(line);
    const expected = frame.nexus_expected_run_id;
    if (typeof expected === "string" && RUN.test(expected) && active?.id === expected &&
        owner.session === session && session.isStreaming) return onLine(line);
    writeProtocol(JSON.stringify({ id: frame.id, type: "response", command: "abort", success: false,
      nexus_refused_before_abort: true, error: "The reviewed Pi run is stale." }) + "\n");
  };
}
