import { AsyncLocalStorage } from "node:async_hooks";

/** Guard the native queue after Pi's asynchronous input extension handlers. */
export function fenceHostedRpcSteer(owner) {
  const session = owner.session;
  const runPrompt = session._runAgentPrompt.bind(session);
  const steer = session.steer.bind(session);
  const queueSteer = session._queueSteer.bind(session);
  const steering = new AsyncLocalStorage();
  let active;

  function check(run) {
    const signal = session.agent.signal;
    if (!run || active !== run || owner.session !== session || !session.isStreaming || !signal || signal.aborted) {
      throw new Error("The Pi run selected by the steering command has ended.");
    }
  }

  session._runAgentPrompt = async (...args) => {
    const run = {};
    active = run;
    try {
      return await runPrompt(...args);
    } finally {
      if (active === run) active = undefined;
    }
  };

  session.steer = async (text, images, options) => {
    if (options?.source !== "rpc") return steer(text, images, options);
    const run = active;
    check(run);
    return steering.run(run, () => steer(text, images, options));
  };

  session._queueSteer = (text, images) => {
    const run = steering.getStore();
    if (run) check(run);
    return queueSteer(text, images);
  };
}
