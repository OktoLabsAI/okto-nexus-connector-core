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
