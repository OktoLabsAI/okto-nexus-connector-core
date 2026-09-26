# Pi 0.87.1 real control campaign (steer/abort/follow-up/shutdown) — 2026-09-26

User-authorized real provider campaign on Windows/x86_64 against the same
explicitly selected pair recorded in the 0.87.1 observation (Node
`3331e1ff…a5`, CLI `e79626f2…774`), reusing the user's Pi config for
authentication only. Disposable session directory; tools, extensions, skills,
prompt templates, themes and context files disabled; automatic retries
disabled before the first prompt. `tools/probe_pi_controls.py` logs only
event types, ordering and timings — no prompt output, model text, stderr or
credentials.

Observed (three model turns plus one aborted mid-flight):

- **Steer (ID-less, queue semantics):** prompt accepted; `steer` accepted;
  a `queue_update` with a non-empty steering list arrived; at the next turn
  boundary the queue drained (second `queue_update`) and the steer text was
  delivered as a user message (`message_start`/`message_end` after the new
  `turn_start`); the agent continued and settled only at `agent_settled`
  with assistant stop reason `stop`. A follow-up turn started after the
  first settle. This is the real-provider confirmation of the public ID-less
  steer contract: queued next-turn-boundary delivery, terminal only at
  `agent_settled`.
- **Abort:** during a live counting turn, `agent_settled` for the aborted
  turn was observed **before** the `response(abort)` ack returned
  (`abort_settle_before_ack: true`), matching protocol reference §6(b) and
  the connector's settle-gate design. The turn settled; the gate cleared.
- **Follow-up:** a new `prompt` after the aborted settle was accepted and
  settled with stop reason `stop` — cancel preserves the session for a real
  follow-up submit.
- **Shutdown:** `close()` during a live turn returned in 0.013 s and the
  owned process stop was observed well within the 30 s bound.

Scope limits: one machine, one Windows build of Pi 0.87.1, no tools, no
extensions (no real `extension_ui_request` traffic), Linux provider behavior,
version drift, concurrency under sustained load and multi-host consumption
remain unqualified. The native qualification allowlist stays empty; this
campaign does not by itself enable production launches.
