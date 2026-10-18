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

## M4d4a — Physical journal registry foundation

44 installed cases passed, including conflict rollback, concurrent registration,
cancelled observers and storage-full retention. The registry port and SQLite
adapter record creation intent independently of execution/capacity authority.
See [runtime-lifecycle-m4d4.md](runtime-lifecycle-m4d4.md). Host adoption and the
audit frontier remain pending. Consumer vendor pins and global packages still
use M4d3; do not remove the current startup scan based on this registry alone.

## M4d4 — Registry cost evidence

Three additional installed cases measure 1k/10k/100k registrations through the
public port. Exact lookup/page SQL work is constant across those sizes; 100k
representative entries allocate 43,925,504 bytes. This leaves about 22.1 MiB of
the unchanged 64 MiB ledger budget for other metadata, so full mixed-history
budget qualification remains required. See
[runtime-lifecycle-m4d4-cost.md](runtime-lifecycle-m4d4-cost.md). The Core wheel
is unchanged; Nexus/Connector now consume the registry in their M4d4b work.

## M5a — Shared startup refusal foundation

149 installed cases passed; 161 package files verified. Scoped refusal fences
an opening before native admission without granting physical release authority.
Also repaired the stale preopen bundle base hash, with branch-equivalence
regression coverage. See [runtime-lifecycle-m5a.md](runtime-lifecycle-m5a.md).
Connector consumption is still pending and Nexus consumer qualification has
four remote publication failures under investigation. No global rollout or
complete M5 qualification is claimed.

## M5c — Prelease control report contract (foundation)

Core now validates a negotiated current-connection startup-refusal report with
the original no-effect receipt and exact released capacity evidence. The final
installed wheel passed 73 selected control/receipt cases with 162 package files
verified byte for byte. See
[runtime-lifecycle-m5c-contract.md](runtime-lifecycle-m5c-contract.md).
Connector production, Server authenticated acceptance/replay and real UI
qualification remain pending; the global installation is unchanged.

## M3 Pi version-probe deadline (installed real UI checkpoint)

Pi's three-second read-only version probe failed intermittently during the
real Nexus connection wizard. The Pi-specific owned probe now permits ten
seconds. Three source and three isolated installed tests passed, and a
disposable installed Nexus completed the real Pi connection test, two
Meta-harness replies and an automatic post-restart reply with 1/1 ACK. The
first cold session still took about 162 seconds to
become ready; M3/M7 latency work and the full UI gates remain open. See
[runtime-lifecycle-m3-pi-version-probe.md](runtime-lifecycle-m3-pi-version-probe.md).

## M3o — Pi lease rotation at native-action launch

A disposable real UI trace showed a 73-second Pi pre-spawn refusal across a
lease renewal. Focused red/green coverage found that the Pi-specific
native-action owner rejected the new lease ID while the shared opening
authority accepted that rotation. The owner now permits the new ID only with
an advancing serial and stable subject/grant/boot scope. Eight source and
eight installed cases plus one installed bridge case passed. The same Core
wheel is vendored by Nexus and Connector; exact-wheel real UI and M7 latency
qualification are still pending. See
[runtime-lifecycle-m3o-pi-lease.md](runtime-lifecycle-m3o-pi-lease.md).

## M7a — Avoid duplicate Pi content hash during cold prepare

Runtime `prepare` now defers its full build hash; the admitted `open` still
checks the complete identity before capacity reservation and native spawn.
Direct `prepare_launch` callers retain the old validation. 88 source and 11
selected installed tests passed; a real Pi candidate measured 0.651s versus
8.300s for preparation without/with the full hash in one warm-cache run.
Consumer vendors use the same wheel. See
[runtime-lifecycle-m7a-cold-preparation.md](runtime-lifecycle-m7a-cold-preparation.md).

## M7b — Passive Pi reader budget

Core limits passive Pi identity scans to two file readers while admitted opens
retain four; the complete identity is still hashed. 100 source and 100
installed-wheel tests passed. See
[runtime-lifecycle-m7b-passive-budget.md](runtime-lifecycle-m7b-passive-budget.md).

## M4d4g — Mixed ledger budget

At 100,000 paired physical registrations and terminal capacity records, the
ledger allocated 256,573,440 bytes, exceeding the former 64 MiB cap. The
default growth ceiling is now 512 MiB; 15 focused source and 15 installed
tests passed. Terminal-history retirement and the major real UI gate remain
open. See
[runtime-lifecycle-m4d4g-mixed-capacity.md](runtime-lifecycle-m4d4g-mixed-capacity.md).

## M3t — R4 inventory generator consistency

The feature-branch CI stopped before tests because `generate_r4.py --check`
would remove the required `observations` inventory field and its
`HarnessObservation` schema. The generator now emits the existing package
contract byte-for-byte, preserving per-harness pending/present/absent/failed
observations. Both contract generation checks, 41 inventory/bundle/conformance
tests, Ruff and diff checks pass locally. Multi-platform CI qualification is
pending the pushed run; no runtime package contract was changed.
