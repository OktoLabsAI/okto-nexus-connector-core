// Pi emits message_end before appending the same object to its native history.
// Only publish a snapshot when the next microtask can observe that exact new entry.
export function observeHostedPiChat(owner, writeProtocol) {
  const session = owner.session;
  const manager = session.sessionManager;
  const sessionId = session.sessionId;
  session.subscribe((event) => {
    const message = event.message;
    if (event.type !== "message_end" || !["user", "assistant"].includes(message?.role)) return;
    const previous = manager.getLeafId();
    queueMicrotask(() => {
      if (owner.session !== session || session.sessionManager !== manager || session.sessionId !== sessionId) return;
      const entry = manager.getLeafEntry();
      if (entry?.type !== "message" || entry.message !== message || entry.id === previous) return;
      const content = typeof message.content === "string" ? [{ type: "text", text: message.content }] : message.content;
      if (!Array.isArray(content)) return;
      let text = "";
      for (const part of content) {
        if (part?.type !== "text" || typeof part.text !== "string" || !part.text) continue;
        const body = text ? `${text}\n${part.text}` : part.text;
        // Keep an explicit omitted-body marker without cutting a secret in half before redaction.
        if (body.length > 12288 || Buffer.byteLength(body) > 12288) { text = null; break; }
        text = body;
      }
      if (text === "") return;
      writeProtocol(JSON.stringify({ type: "nexus_pi_chat_message", revision: 1, native_session_id: sessionId,
        entry_id: entry.id, role: message.role, text }) + "\n");
    });
  });
}
