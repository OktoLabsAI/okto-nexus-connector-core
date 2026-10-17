# Runtime lifecycle development ledger

Version: **0.0.12**. Branch: **feature/v0.0.12**.

Canonical plan: Nexus repository, `plans/runtime_lifecycle/plan.md` on
`feature/v0.3.1`. Scope: early birth evidence, durable launch intent/fencing,
incremental recovery, shared lifecycle contracts and qualified containment.

## M0 — Baseline validated

Preserve the existing large native-event artifact changes: deterministic payload
references/chunk codec, journal recovery, bounded native framing, secret handling
and final-event projection. Existing installed campaign: 24 Core cases passed;
the three-package integration campaign totaled 106 cases.

2026-10-16 checkpoint: version and wheel metadata agree; consumers pin 0.0.12.
Diff whitespace checks and credential-pattern scan passed. Published in the
baseline commit on this branch; the canonical ledger records its hash next.

The baseline did not close the pre-birth crash window. Do not release uncertain
slots from missing evidence.

## M1 — Birth evidence before handshake (validated)

- Pi, Codex and Claude now notify a shared process-birth recorder immediately
  after obtaining their owned handle, before protocol negotiation.
- Runtime binds the recorder to the original operation/session claim. The
  startup worker waits for the asynchronous journal commit; the event loop and
  sibling openings continue independently.
- Recording failure/timeout is a post-spawn uncertainty, never a retryable
  pre-effect refusal. The adapter retains its handle for containment. A late
  journal commit is not cancelled or interpreted as a successful open.
- After recording, recheck the live opening authority before protocol I/O.
- Tests against the installed wheel: **10 passed** (all three real adapters with
  synthetic subprocess peers; persistence failure, parallel openings, caller
  cancellation, recorder timeout and draining); additional unresponsive Pi
  handshake case **1 passed**, including retained birth evidence after containment.
- Focused source regressions: **39 passed**, covering immutable birth evidence,
  abrupt owner crash, existing factory/opening and prewrite behavior.
- Local evidence: `build/runtime-lifecycle-m1-installed.xml`,
  `build/runtime-lifecycle-m1-handshake.xml`,
  `build/runtime-lifecycle-m1-regression.xml`.
- Wheel/source comparison passed. Core wheel SHA256:
  `d2799bb6249c28fca5e56d9e17862ca1b3f72b15a59c5f9e2d15d509a0d2da8f`.
- Connector installed-consumer gate: **43 passed** (`test_r4_execution.py` and
  `test_r4_daemon_execution.py`). Nexus installed-consumer gate is recorded in
  the canonical ledger when completed.

Scope: Windows native containment, synthetic protocol peers. This does not
qualify real model providers or Linux/macOS execution. The pre-spawn durable
intent and producer fencing window remains M2; no slot release rule was relaxed.
The running user installation was not changed by M1 (only an isolated test env).

User decision on 2026-10-16: breaking changes are allowed. Future shared contracts
may require coordinated upgrades of all three repositories; old-version
interoperability is not an acceptance requirement.

## M2 — Durable intent and fenced recovery (in progress)

M2a foundation validated: immutable launch identity, SQLite CAS state and
nonblocking producer exclusion. Installed Windows campaign: **53 passed**;
dependency validation passed. Details and limitations:
[`runtime-lifecycle-m2a.md`](runtime-lifecycle-m2a.md).
This checkpoint does not yet change runtime startup/recovery or the live install.

M2b validated: atomic opening/intent admission and shared producer controller.
Installed Windows campaign: **80 passed**, including M2a regressions and lost
authority/cancelled waiter/independent sibling scenarios. Dependencies valid.
See [`runtime-lifecycle-m2b.md`](runtime-lifecycle-m2b.md). Native factory and
consumer recovery integration remain pending; live install still uses M1 Core.

M2c validated: managed native adapters consume the admitted identity and shared
producer controller. Installed Windows campaign: **159 passed**, including real
disposable owner crashes at five pre-handshake boundaries, exact-container
containment, sibling isolation and monotonic opening settlement. Dependencies
valid. See [`runtime-lifecycle-m2c.md`](runtime-lifecycle-m2c.md). Consumer
recovery/publication, later crash boundaries and Linux/macOS qualification remain
open; this is not an M2 completion or live rollout.

M2e validated: negotiated never-started resource proof, strict schema projection
and codec composition. **95 installed tests passed**; original receipt outcome
and possible-effect markers remain unchanged. See
[`runtime-lifecycle-m2e.md`](runtime-lifecycle-m2e.md). Consumer recovery uses
the same M2c controller. Live UI results and joint installation belong to the
Nexus canonical ledger; full M2 qualification remains open.

## M3c — Original-owner failed-start recovery (validated checkpoint)

Core now contains an uncertain planned launch even when startup returned no
native handle. A retained worker fences the producer and observes its exact
container before durable slot release. Receipts remain honest and calls are
never replayed. **111 installed tests passed**, including disposable Windows
processes and the real Pi adapter with an injected probe failure. See
[`runtime-lifecycle-m3c.md`](runtime-lifecycle-m3c.md). Nexus/Connector integration,
live rollout and remaining M3 criteria are recorded in the canonical ledger.

## M3e — Scoped local lease failure (validated checkpoint)

43 installed cases passed. See [runtime-lifecycle-m3e.md](runtime-lifecycle-m3e.md) for scope,
artifact identities, initial test failures and remaining boundaries.
No global rollout; M3/M5 remain in progress.

## M3h — Parallel passive observation (validated checkpoint)

59 installed cases passed; 18 POSIX-only cases skipped on Windows. Exact
candidate evidence preserved across four passive measurements of real installed
harnesses. Bounded workers retain cancellation and join ownership. See
[runtime-lifecycle-m3h.md](runtime-lifecycle-m3h.md). Full per-harness publication,
global rollout and M3 qualification remain pending.

## M3i — Independent observation contract and workers (foundation)

117 installed cases passed with the exact Core wheel and isolated interpreter;
158 package files and unchanged campaign inputs verified, dependencies valid.
Per-adapter format-3 coverage, retained independent workers, bounded retries,
refresh frontiers and cancellation-safe join are qualified. See
[runtime-lifecycle-m3i.md](runtime-lifecycle-m3i.md). Nexus/Connector consumption,
selection-baseline migration and joint UI rollout remain pending. Their vendor
wheels and the running global generation 72 still use M3h Core. M3 remains open.

## M4d3 — Released pre-open capacity association

38 installed cases passed with exact package-byte verification. The historical
lookup now accepts an exact released slot observation without granting release
or replay authority. See [runtime-lifecycle-m4d3.md](runtime-lifecycle-m4d3.md).
Consumers are being qualified with this artifact; no global rollout is claimed.
