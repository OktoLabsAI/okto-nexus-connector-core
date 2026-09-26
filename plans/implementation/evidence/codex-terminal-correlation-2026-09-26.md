# Codex terminal correlation fence — 2026-09-26

The Core-owned copied-adapter bridge now requires a Codex `turn/started`
identity before accepting `turn/completed` for a submitted operation. The
terminal turn ID must exactly match the currently observed start. A missing,
malformed or older terminal raises `EVENT_OPERATION_MISMATCH` with possible
effect; it does not settle a newer operation. A bounded set of the 256 most
recent completed Codex turn IDs rejects an immediately replayed start, and
a rejected terminal does not mutate the bridge's cached outcome.

Synthetic bridge tests cover an old and missing terminal after a second
start, plus a replayed old start. An end-to-end runtime/journal test sends a
late old terminal after the second submission: the pump faults and the
second receipt remains `SUBMITTED` with possible effect, not `SUCCEEDED`.
The adapter/docs focused suite passed 24 tests in each local Windows/WSL2 ×
Python 3.11–3.13 environment.

Full Python 3.13 suites passed Windows 576/73 and WSL2 635/14
(passed/skipped), with the expected injected legacy Pi warning. Normalized
Windows/WSL2 builds produced identical artifacts:

- wheel SHA-256: `127c0ea228e630215b3226a4eb499a59e7f0b4a3763c43e72ceb5c9e738f7444`
- sdist SHA-256: `22c8a5eb69c62f3e755e76723f9ad95c729da02f28d8dffb20b126ea0093c301`

The pair passed strict Twine, clean-wheel import and embedded/remote consumer
smokes, and offline wheel/sdist installation on Windows and WSL2 with Python
3.11–3.13. Development release validation returned `publishable: false`.

The bounded replay memory does not prove arbitrary-age native notification
ordering, real Codex turn semantics, provider qualification, or host-side
reconciliation. Those remain open.
