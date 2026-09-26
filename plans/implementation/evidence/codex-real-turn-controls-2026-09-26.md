# Codex 0.157.0 real turn/control campaign — 2026-09-26

User-authorized real provider campaign on Windows/x86_64 against the
explicitly selected native npm Codex executable previously recorded
(`ed1c7b36…b1f`, `codex-cli 0.157.0`), spawned as `codex app-server` with the
user's existing `CODEX_HOME` (authentication only; no credentials read,
copied or printed) and a disposable working directory.
`tools/probe_codex_turn.py` logs only method names, opaque thread/turn IDs,
turn statuses and timings — never prompt output, model text, stderr or
secrets.

Observed (three model turns on one thread):

- **Handshake/thread:** `initialize` → `initialized` → `thread/start`
  succeeded; compatibility observed 0.157.0; MCP-server startup
  notifications, `skills/changed` and `thread/status/changed` were
  classified without disturbing turn correlation.
- **Plain turn:** `turn/started` (native turn ID observed) → `item/started`/
  `item/completed` → `item/agentMessage/delta` stream → `turn/completed`
  with status `completed`. Acceptance of `turn/start` was never treated as
  the terminal.
- **Steer with expected native turn ID:** `turn/steer` with
  `expectedTurnId` naming the live turn was accepted mid-turn; the turn
  continued with further items and a new agent message after the steer;
  `turn/completed` status `completed`.
- **Interrupt with expected native turn ID:** `turn/interrupt` targeted the
  live turn; `turn/completed` arrived with status `interrupted` — a real
  cancellation, not a no-op.
- **Close:** bounded in 0.05 s.

Scope limits: one machine, one Windows build, one thread, no approval/input
requests exercised (no tools were invoked by the prompts), no `thread/resume`
(still unqualified), Linux/macOS and version drift remain unqualified. The
native qualification allowlist stays empty; this campaign does not by itself
enable production launches.
