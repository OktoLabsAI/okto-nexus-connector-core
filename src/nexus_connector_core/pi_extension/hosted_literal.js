const REWRITE_HOOKS = ["input", "before_agent_start", "context", "before_provider_request"];

/** Dispatch an explicit literal only on the reviewed, idle and unmodified prompt path. */
export function fenceHostedRpcLiteral(session) {
  const prompt = session.prompt.bind(session);
  session.prompt = async (message, options) => {
    if (typeof message === "string") return prompt(message, options);
    if (!message || options?.source !== "rpc" || message.kind !== "nexus_hosted_literal" ||
        Object.keys(message).length !== 2 || typeof message.text !== "string" || !message.text ||
        options.images !== undefined || options.streamingBehavior !== undefined) {
      throw new Error("Literal Pi input is malformed.");
    }
    if (session.isStreaming || session.isCompacting || session._isEmittingAgentSettled ||
        REWRITE_HOOKS.some((hook) => session._extensionRunner.hasHandlers(hook))) {
      throw new Error("Literal Pi input is unavailable.");
    }
    return prompt(message.text, { ...options, expandPromptTemplates: false });
  };
}
