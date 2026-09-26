# Claude 2.1.282 real stream-json turn/control campaign — 2026-09-26

User-authorized real provider campaign on Windows/x86_64 against the
explicitly selected local `claude.exe` previously recorded
(`fc0e3af0…84e`, version 2.1.282), spawned in
`-p --output-format stream-json --input-format stream-json --verbose
--include-partial-messages` mode with the user's existing home
(authentication only; no credentials read, copied or printed) and a
disposable working directory. `tools/probe_claude_turn.py` logs only event
type prefixes, result subtypes and timings — never prompt output, model
text, stderr or secrets.

Observed (three model turns over one process):

- **Plain turn:** `system:init`/`system:status`, `stream_event` deltas,
  `assistant` message and a terminal `result:success`. The result frame —
  not process liveness — is the terminal.
- **Multi-turn:** a second user message on the same stream-json process
  produced its own init/status/deltas and a second `result:success`.
- **Interrupt while generating:** after deltas were observed, the adapter's
  native interrupt landed (`control_response:success`) and the turn ended
  with `result:error_during_execution` — an honest interrupted terminal,
  not a fabricated success. A `user_echo` of the in-flight message was
  preserved as its own event class.
- **Shutdown:** process stop observed after the final result; `close()`
  bounded in 1.03 s.

Scope limits: one machine, one Windows build, no approval/input or
can_use_tool traffic (prompts invoked no tools), requesting-phase control
rejection remains covered by synthetic pre-write tests, queue/interrupt-then
-reprompt semantics and Linux/macOS/version drift remain unqualified. The
native qualification allowlist stays empty; this campaign does not by itself
enable production launches.
