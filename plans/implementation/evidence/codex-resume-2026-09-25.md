# K05.2 Codex thread resume boundary — 2026-09-25

The [official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server)
specifies `thread/resume` with a previously recorded `thread.id` and says its
response has the `thread/start` shape. It does not make resume a proof that an
earlier effect is deduplicated.

The Core-owned Codex adapter now accepts an explicit `resume_thread_id`, sends
`thread/resume` with the pinned 0.157.0 schema's supported parameters, and
rejects a different returned ID, an explicitly active/system-error thread,
start-only overrides, malformed IDs, and a thread already bound on the same
connection. New threads still use `thread/start`. The factory exposes resume
only through an optional trusted-host callback returning `CodexResumeGrant`.
It checks the new Core session, Server/executor/binding/agent/workspace scope,
owner generation, binary/root/profile fingerprints, observed terminal state,
observed persisted rollout, and exclusive ownership **before spawning** the
native connector. The host must actually establish the latter three facts;
the Core cannot infer them from a native thread ID.

Synthetic tests passed on Windows and WSL2 for the real outbound resume
shape against the pinned generated schema, matching-ID acceptance, mismatched
or active response refusal, valid grant forwarding, and wrong-agent/missing-
rollout-grant refusal.

A read-only native probe on the selected Codex 0.157.0 Windows/x86_64 binary
created a thread in a disposable `CODEX_HOME`, closed that connection, and
attempted resume on another. The native server rejected it with `no rollout
found`; neither path sent `turn/start` or made a model request. This establishes
that **this no-turn probe did not create a resumable persisted rollout**, not
that all 0.157.0 threads are unresumable. A persisted real-turn fixture and
host integration are still required to qualify successful cross-process
resume, event replay, exclusivity, and deduplication boundaries. The effective
qualified-build set remains empty.
