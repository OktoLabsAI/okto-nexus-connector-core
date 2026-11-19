import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import net from "node:net";

const MAX_HANDSHAKE = 768;
const MAX_BACKLOG = 256 * 1024;
const MAX_CHUNK = 12 * 1024;
const MAX_EDITOR_FRAME = 16 * 1024 + 128;
const MAX_INSERT = 4 * 1024;
const EDITOR_KEYS = new Map([
  ["insert", ""], ["enter", "\r"], ["newline", "\n"], ["backspace", "\x7f"], ["delete", "\x1b[3~"],
  ["left", "\x1b[D"], ["right", "\x1b[C"], ["up", "\x1b[A"], ["down", "\x1b[B"],
  ["home", "\x1b[H"], ["end", "\x1b[F"], ["snapshot", null], ["clear", null],
]);
const decoder = new TextDecoder("utf-8", { fatal: true });
const VISIBLE_EVENTS = new Set([
  "agent_start", "turn_start", "agent_end", "message_start", "message_update", "message_end",
  "tool_execution_start", "tool_execution_update", "tool_execution_end",
]);

// Only the text, style, cursor movement and erase sequences needed by the
// transcript cross this boundary. Keep control-string state across writes.
export class TerminalOutputFilter {
  state = "text";
  parameters = "";
  filter(text) {
    let output = "";
    for (const char of text) {
      if (this.state === "string" || this.state === "stringEsc") {
        if (char === "\x07" || char === "\x9c" || (this.state === "stringEsc" && char === "\\")) this.state = "text";
        else this.state = char === "\x1b" ? "stringEsc" : "string";
        continue;
      }
      if (char === "\x1b") {
        this.state = "esc";
        continue;
      }
      if (this.state === "esc") {
        this.state = char === "[" ? "csi" : "]P_X^".includes(char) ? "string" : /[ -/]/.test(char) ? "escapeBody" : "text";
        this.parameters = "";
        continue;
      }
      if (this.state === "escapeBody") {
        if (!/[ -/]/.test(char)) this.state = "text";
        continue;
      }
      if (this.state === "csi" || this.state === "discardCsi") {
        if (char >= "@" && char <= "~") {
          if (this.state === "csi" && (/^[0-9;:]*$/.test(this.parameters) && "mABCDEFGHfJK".includes(char)
              || this.parameters === "?25" && "hl".includes(char))) {
            output += "\x1b[" + this.parameters + char;
          }
          this.state = "text";
        } else if (this.parameters.length >= 64 || !/[0-9;:?]/.test(char)) {
          this.state = "discardCsi";
        } else {
          this.parameters += char;
        }
        continue;
      }
      if ("\x90\x98\x9d\x9e\x9f".includes(char)) this.state = "string";
      else if (char === "\x9b") { this.state = "csi"; this.parameters = ""; }
      else if ("\r\n\t\b".includes(char) || char >= " " && !(char >= "\x7f" && char <= "\x9f")) output += char;
    }
    return output;
  }
}

class TranscriptTerminal {
  kittyProtocolActive = false;
  filter = new TerminalOutputFilter();
  constructor(socket, columns, rows, ownsSession) {
    this.socket = socket;
    this.columns = columns;
    this.rows = rows;
    this.ownsSession = ownsSession;
  }
  start() {} // The observer never registers a terminal input handler.
  stop() {}
  async drainInput() {}
  setTitle() {}
  setProgress() {}
  moveBy(lines) { if (lines) this.write(`\x1b[${Math.abs(lines)}${lines > 0 ? "B" : "A"}`); }
  hideCursor() { this.write("\x1b[?25l"); }
  showCursor() { this.write("\x1b[?25h"); }
  clearLine() { this.write("\r\x1b[2K"); }
  clearFromCursor() { this.write("\x1b[0J"); }
  clearScreen() { this.write("\x1b[2J\x1b[H"); }
  write(text) {
    if (this.socket.destroyed) return;
    if (!this.ownsSession() || text.length > MAX_BACKLOG / 4) { this.socket.destroy(); return; }
    const bytes = Buffer.from(this.filter.filter(text));
    for (let start = 0; start < bytes.length; start += MAX_CHUNK) {
      const frame = JSON.stringify({ type: "output", bytes: bytes.subarray(start, start + MAX_CHUNK).toString("base64") }) + "\n";
      if (this.socket.writableLength + frame.length > MAX_BACKLOG) { this.socket.destroy(); return; }
      this.socket.write(frame);
    }
  }
}

function proof(key, kind, challenge, id, columns, rows) {
  return createHmac("sha256", key).update([kind, challenge, id, columns, rows].join("\n")).digest("hex");
}

function validAttach(value, key, challenge, id) {
  const kind = value?.revision === 2 ? "attach.edit" : "attach";
  return value && Object.keys(value).length === 6 && value.type === "attach" && [1, 2].includes(value.revision) && value.session_id === id &&
    Number.isInteger(value.columns) && value.columns >= 24 && value.columns <= 300 &&
    Number.isInteger(value.rows) && value.rows >= 8 && value.rows <= 120 &&
    typeof value.proof === "string" && /^[0-9a-f]{64}$/.test(value.proof) && timingSafeEqual(
      Buffer.from(value.proof, "hex"), Buffer.from(proof(key, kind, challenge, id, value.columns, value.rows), "hex"));
}

function validText(text, limit) {
  return typeof text === "string" && text.length > 0 && Buffer.byteLength(text) <= limit &&
    !/[\x00-\x08\x0b-\x1f\x7f-\x9f\uD800-\uDFFF]/u.test(text);
}

/** One private renderer subscriber, bound to the exact session already held by RPC. */
export async function startHostedRenderer(InteractiveMode, owner, key) {
  if (!/^[0-9a-f]{64}$/.test(key)) throw new Error("Missing private Pi presentation key");
  const session = owner.session;
  const id = session.sessionId;
  const ownsSession = () => owner.session === session && session.sessionId === id;
  const observerHost = { session, setBeforeSessionInvalidate() {}, setRebindSession() {} };

  class TranscriptMode extends InteractiveMode {
    // Mount only the transcript and optional draft editor. The owner keeps its
    // existing RPC tools, extension UI bindings and lifecycle.
    openTranscript(socket, terminal, editing) {
      let redraw;
      const draw = () => {
        if (socket.destroyed) return;
        try {
          const children = this.chatContainer.children;
          if (children.length > 96) children.splice(0, children.length - 96);
          const lines = this.renderer.render(terminal.columns).slice(-terminal.rows);
          terminal.write("\x1b[2J\x1b[H" + lines.join("\r\n"));
        } catch { socket.destroy(); }
      };
      // Use Pi's layout and message components. The private viewer owns the
      // frame flush so vendor console crash logging cannot take over the owner.
      this.renderer.requestRender = () => {
        if (redraw || socket.destroyed) return;
        redraw = setImmediate(() => { redraw = undefined; draw(); });
      };
      socket.once("close", () => clearImmediate(redraw));
      const components = [this.documentContainer, this.pendingMessagesContainer, this.statusContainer];
      if (editing) {
        this.defaultEditor.onSubmit = (text) => { this.submission = text; };
        components.push(this.editorContainer);
        this.ui.setFocus(this.defaultEditor);
      }
      this.mountInteractiveTui(this.renderer, components);
      this.isInitialized = true;
      this.renderSessionEntries(this.sessionManager.buildContextEntries().slice(-48));
      this.renderer.requestRender();
    }
    editDraft(frame, sequence) {
      if (!frame || Object.keys(frame).length !== 4 || frame.type !== "key" ||
          frame.sequence !== sequence || !EDITOR_KEYS.has(frame.key) ||
          (frame.key === "insert" ? !validText(frame.text, MAX_INSERT) : frame.text !== null)) {
        throw new Error("Invalid renderer editor frame");
      }
      const { key, text } = frame;
      const insert = key === "insert" ? text : key === "newline" ? "\n" : null;
      const editor = this.defaultEditor;
      const before = editor.getExpandedText?.() ?? editor.getText();
      const limitReached = insert !== null && Buffer.byteLength(before) + Buffer.byteLength(insert) > MAX_CHUNK;
      this.submission = undefined;
      if (key === "clear") {
        editor.setText("");
        this.renderer.requestRender();
      } else if (!limitReached && key !== "snapshot") {
        editor.handleInput(insert === null ? EDITOR_KEYS.get(key) : "\x1b[200~" + insert + "\x1b[201~");
        this.renderer.requestRender();
      }
      const draft = key === "snapshot" ? before : this.submission;
      if (draft && (key !== "enter" && key !== "snapshot" || !validText(draft, MAX_CHUNK))) {
        throw new Error("Invalid editor submission");
      }
      return { type: "edited", sequence, draft: draft ? Buffer.from(draft).toString("base64") : null,
               limit_reached: limitReached };
    }
    getRegisteredToolDefinition() { return undefined; } // No extension renderer callbacks.
    maybeSuggestBugReport() {}
  }

  let active;
  const server = net.createServer({ pauseOnConnect: true }, (socket) => {
    socket.on("error", () => socket.destroy());
    if (active || !ownsSession()) { socket.destroy(); return; }
    socket.setTimeout(3000, () => socket.destroy());
    const challenge = randomBytes(32).toString("hex");
    socket.write(JSON.stringify({ type: "challenge", revision: 1, challenge }) + "\n");
    let pending = Buffer.alloc(0);
    let mode;
    let editing = false;
    let sequence = 0;
    let unsubscribe;
    let scheduled;
    const events = [];
    socket.once("close", () => {
      if (active === socket) active = undefined;
      unsubscribe?.();
      clearImmediate(scheduled);
      events.length = 0;
      try { mode?.stop(); } catch { /* Viewer cleanup stays local to the attachment. */ }
    });
    socket.on("data", (chunk) => {
      if ((mode && !editing) || chunk.length + pending.length > (mode ? MAX_EDITOR_FRAME : MAX_HANDSHAKE) ||
          !ownsSession()) { socket.destroy(); return; }
      pending = Buffer.concat([pending, chunk]);
      const lf = pending.indexOf(10);
      if (lf < 0) return;
      try {
        if (lf !== pending.length - 1) { socket.destroy(); return; }
        const request = JSON.parse(decoder.decode(pending.subarray(0, lf)));
        pending = Buffer.alloc(0);
        if (mode) {
          if (sequence >= 2 ** 31 - 1) { socket.destroy(); return; }
          const reply = JSON.stringify(mode.editDraft(request, ++sequence)) + "\n";
          if (socket.writableLength + reply.length > MAX_BACKLOG) { socket.destroy(); return; }
          socket.write(reply);
          return;
        }
        if (active || !validAttach(request, key, challenge, id)) { socket.destroy(); return; }
        active = socket;
        const { columns, rows } = request;
        editing = request.revision === 2;
        const terminal = new TranscriptTerminal(socket, columns, rows, ownsSession);
        mode = new TranscriptMode(observerHost, { terminal, tuiMode: "transcript" });
        mode.openTranscript(socket, terminal, editing);
        const ready = editing ? "ready.edit" : "ready";
        socket.write(JSON.stringify({ type: "ready", proof: proof(key, ready, challenge, id, columns, rows) }) + "\n");
        socket.setTimeout(0);
        unsubscribe = session.subscribe((event) => {
          if (!ownsSession() || events.length >= 32) { socket.destroy(); return; }
          if (!VISIBLE_EVENTS.has(event.type) || socket.destroyed) return;
          events.push(event);
          if (!scheduled) scheduled = setImmediate(async () => {
            try {
              while (events.length && !socket.destroyed) {
                const current = events.shift();
                // Pi can decorate an aborted message with an error string.
                const projected = current.type === "message_end" ? { ...current, message: { ...current.message } } : current;
                await mode.handleEvent(projected);
              }
            } catch { socket.destroy(); }
            finally { scheduled = undefined; }
          });
        });
      } catch { socket.destroy(); }
    });
    socket.resume();
  });
  server.maxConnections = 4; // Bound unauthenticated handshakes separately from the viewer slot.
  server.on("error", () => active?.destroy());
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen({ host: "127.0.0.1", port: 0, exclusive: true, backlog: 1 }, () => {
      server.off("error", reject);
      resolve();
    });
  });
  server.unref();
  return server.address().port;
}
