# Implementation status — 2026-09-25

The current Pi 0.87.1 integration slice is closed in
[`milestone-pi-0871-2026-09-26.md`](milestone-pi-0871-2026-09-26.md).
This does not close the integral K00–K11 plan or enable production release.

Source baseline: local `D:\\projetos\\Techridy\\okto_labs_okto_nexus`, branch
`feature/v0.2.0`, HEAD `7ed52c22865a92c3768bc32508ed9e35dc5efdc3`.
The source worktree contains unrelated preexisting changes in static assets and
`.nexus-policy-guardrail-test/`; none were used or changed here.

| Phase | Status | Evidence / next gate |
|---|---|---|
| K00 | IN_PROGRESS | Separate src-layout project and local wheel/sdist build. A read-only Nexus baseline inventory records SHA-256 for the four copied/adapted adapters, shared helpers, excluded application supervisor/domain/ports, legacy tests, license text and runtime dependencies. Clean-wheel import audit rejects app imports and undeclared external imports, including MCP/dashboard/embedding libraries. Read-only, SHA-pinned CI defines six Windows/Ubuntu × Python 3.11–3.13 test/build jobs plus a dependent runtime-SBOM job; hosted jobs remain NOT_RUN. The normalized build entry point produced byte-identical wheel/sdist in all six local Windows/WSL2 × Python 3.11–3.13 builds. A CycloneDX 1.6 inventory of an isolated installed wheel passes locally on Windows and WSL2. License text/legal review and signed release provenance remain pending. |
| K01 | IN_PROGRESS | Public types, strict revision gate, deterministic Core-owned contract generator, schemas for all 20 NXL frame families plus intent/event/error/inventory/capability/HTTP response, positive/negative fixtures, hash vectors, and hashed manifest. RFC 8785 canonicalization handles floats; the bundled-schema frame codec enforces a 1 MiB hard wire limit, exact revision, closed fields and event/inventory/unknown-receipt invariants before effect. The unpublished development r3 submit frame carries conditional `expected_turn_id` and its `intent_hash` is recomputed over semantic fields; downstream repinning is required. Pure receipt, event batch/ACK, inventory and lease producer-consumer components handle terminal evidence without fabricated stages, uncertain effects, contiguous durable watermark, bounded gaps/recent duplicate hashes, gap-free inventory deltas and conservative monotonic lease grants. An offline installed-wheel consumer verifier now checks a pinned manifest, resources, schemas, fixtures and vectors, with explicit opt-in for the partial dev bundle. Real consumer-host durable commit/replay integration, agreement on per-attempt lease ID semantics and release compatibility remain pending. |
| K02 | IN_PROGRESS | Four native adapter files copied into Core with local neutral imports. Adapted legacy suites: Codex 32, Pi 27, Claude stream 29 pass on Windows; attach 57 skipped for POSIX. Typed async RuntimeCore facade and private adapter bridge now exist. A fixed metadata-first registry owns adapter IDs, native kinds, executable names and platform gates; the factory imports only a selected static class lazily after qualification. Real native qualification and Server/Connector cutover pending. |
| K03 | IN_PROGRESS | Trusted local PATH/explicit selection, bounded PE/ELF/Mach-O architecture parsing, sealed selected-Claude/Pi/Codex version probes, argv realization, drift and minimal local secret environment tested. An explicitly selected native npm Codex executable was observed locally as 0.157.0/win32/x86_64; PATH wrappers remain rejected. JSON plan/update/removal and narrow Codex TOML plan/update/removal preserve third-party entries and require host-supplied exact ownership proof. Local file apply uses an adjacent cross-process advisory lock, reread/hash CAS, owner-only backup mode on POSIX, temporary-file replace and explicit post-replace uncertainty. Native build qualifications require exact kind/version/platform/architecture/fingerprint; effective set remains empty. Non-cooperating writers remain a race at final replace, Windows backup ACL verification belongs to the trusted host, and actual Pi/provider qualification and broader template semantics remain pending. |
| K04 | IN_PROGRESS | SQLite admission, stage transitions, effect uncertainty, Server/executor-scoped operation/session keys, atomic terminal event+receipt, persistent event sequence and contiguous watermark tested. Duplicate admission also requires the same session ID, preventing same ID/hash from returning another session's receipt. A reusable Journal-port conformance kit exercises this and unknown/no-write/terminal/ACK/replay/compaction semantics on the reference journal; actual Server adapter parity remains pending. Codex adapter refusals explicitly proven before native write now cross the bridge as durable safe failure and leave its turn slot reusable; unmarked errors remain uncertain. Abrupt child-process exit at eight journal boundaries now passes on Windows and WSL2, including rollback of an uncommitted insert and survival of committed unknown/terminal/ACK facts. Transactional event byte/item quotas and critical reservation gate work at 80%; concurrent writers, restart accounting and bounded-page replay tested. Durable-ingress ACK and bounded compaction of ACKed event bodies preserve stream sequence across restart and release logical quotas. Physical DB/WAL/SHM status, admission headroom, main-file page limit and explicit non-waiting WAL checkpoint now tested; a pinned reader can still grow WAL, so no hard filesystem cap is claimed. Async runtime facade covers admission, durable native event pump, monotonic lease renewal/CAS/revocation, expiry/grace close, inspect/reconcile, close and basic shutdown with injected backend. Per-session normal/control locks let urgent interrupt bypass a pending native submit while serializing close/shutdown against both; a per-session open reservation keeps unrelated urgent controls responsive and shutdown waits for reserved launches. Open now waits for the Core event pump to start, and an immediate pump failure leaves an unknown—not positive—open outcome. Configurable ceilings bound concurrent launch attempts (default 8) and per-runtime owned/uncertain sessions (default 32); proven prelaunch refusal records safe failure without consuming the owned slot. Extracted Windows Job Object and Linux guardian backends; Windows abrupt-supervisor-death and WSL2 Linux abrupt-owner-death with an escaped descendant passed. Hard WAL bound/automatic maintenance, persisted process ownership/lease, host-wide physical tree limit, full reconnect fencing, broader Linux matrix and finite qualified shutdown reports pending. |
| K05–K08 | IN_PROGRESS | Four copied adapters remain unqualified for real providers. The Core-owned Codex adapter now sends `initialized` after `initialize`, uses a neutral/host-supplied validated client identity, and completed a no-turn `thread/start` against explicitly selected native Codex 0.157.0 on Windows/x86_64. That build's generated nonexperimental v2 JSON Schema bundle is copied into Core. A trusted-host resume-grant seam checks ownership/profile/persisted-rollout evidence before native `thread/resume`; synthetic resume tests pass, while a real no-turn cross-process probe found no persisted rollout and did not qualify resume. Claude requesting-phase interrupt/steer refuse before native write and the Core journal records a durable safe failure. Public `expected_turn_id` now reaches the native command; idle/stale targets fail before write, with `STALE_TURN` for an obsolete target. Public `turn.steer` is admitted only for Codex with explicit native turn ID and action authorization; Claude/Pi remain unsupported for this action. Synthetic peer and public API tests pass on Windows and WSL2; the POSIX attach suite exposed and then verified a fixed `CONTENT_TOO_LARGE` extraction regression. Real-turn/provider/platform qualification remains pending. Local Claude 2.1.282 and native Codex 0.157.0 were observed on win32/x86_64 without enabling capabilities; Pi remains absent. |
| K09 | IN_PROGRESS | Declarative direct HTTP target validation requires explicit origin allowlist and local loopback reachability. Qualified-format Codex/Claude templates emit native HTTP-client entries with an environment-variable name bound to a local `mcp-cap:` ref, never a literal token or MCP helper. Codex TOML and Claude JSON entries now compose with owner-proof merge. The local environment builder resolves only approved refs, and the factory/adapter seam admits only the derived MCP token variable while blocking other `NEXUS_*` values. A typed, scoped, non-MCP native-action bridge delegates context/get, handoff/claim and handoff/complete to an injected canonical backend with scope, lease, revision and payload gates. A dependency-free Pi extension with three explicit native tools and a narrow Core-owned loopback JSONL ingress are included in wheel/sdist and tested end-to-end with a fake canonical backend; typed adapter/factory launch injects only the approved port/capability/session and local extension path. Core-owned, connection-scoped redaction scrubs copied-adapter and ingestor events before journal/publication, with bounded split-secret holdback and raw output-payload withholding. They do not implement inbox or governance. Real native-format/redaction qualification, production host issuance/wiring, real Pi execution and multi-host integration remain pending. |
| K10 | IN_PROGRESS | Journal crash cuts and six kernel effect-boundary cuts run in child processes on Windows and WSL2, proving pre/post-marker/receipt state and no automatic replay of the same intent after a synthetic external effect. Five additional cuts use a real Core-owned local LF child process across spawn, an unterminated stdin fragment, acknowledged complete write and receipt commit; Windows process handles/Linux pidfds verify owner-death reaping, and duplicate admission never replays. SQLite page exhaustion now proves typed full errors, no phantom facts and recovery after capacity returns on both local OSes. Real provider ambiguity, crashes inside spawn/kernel-space partial writes, actual filesystem-full and pinned-WAL pressure, saturation/fairness, full platform matrix and host-adapter parity campaigns remain pending. |
| K11 | IN_PROGRESS | Read-only validation CI and SBOM artifact retention are staged locally but not run remotely. Independent embedded/remote synthetic consumer smokes run against the same clean installed wheel on Windows and WSL2, without application imports. The local Windows/WSL2 × Python 3.11–3.13 matrix passes full suites, offline wheel/sdist installs and byte-identical builds; hosted runners, physical isolation and real consumers remain unverified. Public API/lifecycle/compatibility/adapter/security guides are Core-owned and included in the sdist, with export/registry/link drift tests; provider qualification and published compatibility ranges remain open. A manual, main-only release workflow stages strict package validation and exact artifact-hash checks before a separate PyPI environment/OIDC publish job, gated by commit/version/license-review secrets. This workflow is unexecuted; environment reviewers, legal review, trusted-publisher configuration, real consumer integration and publication remain pending. |

K04 native failure update: Pi, Claude stream and attach now mark only
adapter refusals proven before their protocol write; the bridge journals
these as safe failures. Transport/write errors remain uncertain. Specific
paths and limits are recorded in the native pre-write evidence file.

K04/K10 lease timing update: the standalone kernel and local runtime now
fail closed on a decreasing or non-finite injected monotonic clock. Synthetic
tests prove no new native submit, no new journal admission and owned cleanup;
the same fence prevents a scoped native-action grant from reviving after
rollback. Windows and WSL2 suites passed;
restart/reboot and cross-host clock qualification remain open. Details are in
`plans/implementation/evidence/lease-clock-rollback-2026-09-25.md`.

K10 frame input update: the encoder preflights oversized/cyclic host objects
before JCS allocation and rejects invalid requested limits; adversarial JSON
cases now include deep nesting, escaped duplicate keys, invalid Unicode and
oversized numbers. The broader TK-39 fuzz/provider campaign remains open.

K10 hostile configuration update: all journal byte/row limits now require
signed-64-bit integral values (excluding booleans) before database creation;
lease and shutdown timing reject non-finite/untyped inputs before lifecycle
effects. Targeted tests pass on Windows/WSL2 × Python 3.11–3.13. This is
partial TK-39 evidence, not a provider/parser fuzz qualification. See
`plans/implementation/evidence/hostile-configuration-2026-09-26.md`.

K10 native-JSON update: Codex, Pi and Claude-stream now reject duplicate
keys/non-finite constants on bounded native stdout lines. Codex also surfaces
non-object JSON-RPC messages and survives deep-parser recursion without
losing the real terminal. Scripted subprocess tests pass on Windows/WSL2 ×
Python 3.11–3.13; real provider fuzz qualification remains open. See
`plans/implementation/evidence/native-hostile-json-2026-09-26.md`.
The stable final Python 3.13 suites passed at Windows 450/73 and WSL2
509/14 (passed/skipped); both retain the expected injected legacy Pi warning.

K10 Unicode/streaming update: the strict JSON ingress now rejects unpaired
surrogates and out-of-range interoperable integers; deep host config JSON
maps to `PROFILE_DRIFT`. The Core JSONL decoder bounds chunk bytes and
returned records per feed. Twenty-one focused cases passed on Windows/WSL2 ×
Python 3.11–3.13. This remains partial TK-39, not real-provider fuzz closure.
The final Python 3.13 full suites passed at Windows 462/73 and WSL2 521/14
(passed/skipped), with the expected injected legacy Pi warning.

K06.1 Pi framing update: Core now frames Pi stdout by bounded bytes/LF
before strict UTF-8 decoding; CRLF, fragmented multibyte Unicode, internal
Unicode separators and invalid-byte recovery passed against a subprocess
peer on Windows/WSL2 × Python 3.11–3.13. Real Pi/version/backpressure
qualification remains open. See
`plans/implementation/evidence/pi-byte-framing-2026-09-26.md`.
The stable Python 3.13 full suites passed at Windows 465/73 and WSL2
524/14 (passed/skipped), with the expected injected legacy Pi warning.

K06.2 Pi correlation update: a timed-out command or ambiguous write now
fences the ID-less transport against a later same-verb reply being mistaken
for a new command. New attempts fail before write with `not_sent` evidence;
late replies remain unmatched diagnostics. Focused subprocess tests passed
on Windows/WSL2 × Python 3.11–3.13. Real Pi ID-echo/version qualification
and concurrent out-of-order support remain open. See
`plans/implementation/evidence/pi-response-correlation-fence-2026-09-26.md`.
The stable Python 3.13 full suites passed at Windows 467/73 and WSL2
526/14 (passed/skipped), with the expected injected legacy Pi warning.

K06.3 Pi terminal correlation update: the Core-owned bridge requires
`agent_start` during the active submit before ID-less `agent_settled` may
settle its receipt. A stale terminal before the new start faults the pump and
leaves the submit unsettled. Contained Pi peer and focused bridge tests
passed 30 cases across local Windows/WSL2 × Python 3.11–3.13. Arbitrarily
delayed start/terminal pairs remain ambiguous without a native ID; real Pi
qualification remains open. See
`plans/implementation/evidence/pi-terminal-start-fence-2026-09-26.md`.
Full Python 3.13 suites passed Windows 588/73 and WSL2 647/14
(passed/skipped), the latter on a quiet rerun after an unrelated 0.3-second
Codex handshake timeout under concurrent artifact work. Matching normalized
artifacts passed strict Twine, clean-wheel consumers and six-environment
offline installation; publication remains disallowed.

K06.1/K06.2 installed Pi update: user-supplied Windows Pi 0.87.1 answered
a no-turn `get_state` with an echoed request ID, cleanly, using explicit
Node/CLI paths and disposable offline configuration. The copied adapter also
passed a no-turn readiness handshake. Exact 0.87.1 now uses bounded
ID-and-verb correlation, while the older ID-less path remains serialized;
synthetic out-of-order and late-response tests pass. The supplied `bin/pi`
is a shell launcher, so production qualification of the selected Node/CLI
pair and broader provider behavior remain open. See
`plans/implementation/evidence/pi-0.87.1-rpc-observation-2026-09-26.md`.
With explicit user approval, one Windows Pi 0.87.1 provider turn without
tools or automatic retries reached `agent_start` and `agent_settled` with
assistant stop reason `stop`; only event metadata was retained. Focused
Pi/bridge tests passed 32 cases across the six local OS/Python combinations;
full Python 3.13 suites passed Windows 590/73 and WSL2 649/14
(passed/skipped). Controls, error paths, real extension UI, Linux provider
behavior and production Node/CLI build qualification remain open.
The matching normalized Windows/WSL2 wheel and sdist passed development
release validation, strict Twine, clean-wheel consumers and offline
installation/resource checks in all six local OS/Python combinations.
The development version remains non-publishable.

K03.2 selected Pi launch update: `candidate_pi_node_cli` now accepts an
explicitly trusted Node executable and the installed Pi package CLI entry
point, never the Windows `sh` launcher. A composite fingerprint binds both
paths and file contents; version observation and prepare/open drift checks
revalidate both. The selected local 0.87.1 installation passed a no-turn
version probe and prepared-argv verification on Windows/x86_64. Focused
synthetic selection/probe tests passed Windows 14 and WSL2 13/1
(passed/skipped). The exact build is still not in the native qualification
allowlist; this does not enable production launch.
Complete Python 3.13 suites passed Windows 593/73 and WSL2 652/14
(passed/skipped); normalized Windows/WSL2 artifacts matched and passed
strict Twine, clean-wheel consumers and six-environment offline installs.
See `plans/implementation/evidence/pi-node-cli-selection-2026-09-26.md`.

K06.2/K06.3 Pi readiness/error update: the copied adapter's default version
probe now uses the selected Node + package CLI pair, not the Node version.
A no-turn probe against installed Pi 0.87.1 passed without an override and
selected ID-echo correlation. A rejected native `prompt` response now fails
the Core send after emitting its error event; the public runtime/journal
keeps `OUTCOME_UNKNOWN` with possible effect instead of a false `SUBMITTED`
receipt. This is not a pre-write refusal and cannot be replayed
automatically. See
`plans/implementation/evidence/pi-prompt-rejection-and-version-probe-2026-09-26.md`.
The same rule now covers rejected native `steer` and `abort` responses;
contained-peer tests pass, and the public runtime keeps rejected `abort`
as possible-effect unknown. Public Pi steer is still unavailable pending
an ID-less target/queue contract.
Focused Pi/bridge tests passed 68/1 (passed/skipped) in each of the six
local OS/Python environments. Full Python 3.13 suites passed Windows
598/73 and WSL2 657/14 (passed/skipped); normalized artifacts matched and
passed strict Twine, clean-wheel consumers and six-environment offline
installation. Development publication remains disallowed.

K04/K10 native-history fairness update: Codex's shared transient replay now
has per-session 512-event/1 MiB ceilings within the global 2,048-event/4 MiB
budget. A noisy session evicts its own oldest replay before a quiet session's
events; explicit replay-expired semantics remain. Seven targeted tests passed
on Windows/WSL2 × Python 3.11–3.13. This is partial TK-40, not sustained
multi-session provider or slow-subscriber qualification. See
`plans/implementation/evidence/native-history-fairness-2026-09-26.md`.
The stable Python 3.13 full suites passed at Windows 474/73 and WSL2
533/14 (passed/skipped), with the expected injected legacy Pi warning.

K04/K10 slow-subscriber isolation update: overflow of a Codex subscriber
now detaches only that bounded queue, leaving the shared process and quiet
sessions running. The affected stream reports an explicit gap; Core marks
only its binding faulted and retains ownership. Scripted peer and runtime
tests passed on Windows/WSL2. Sustained real-provider TK-40 qualification
remains open. See
`plans/implementation/evidence/codex-slow-subscriber-isolation-2026-09-26.md`.
The stable Python 3.13 full suites passed at Windows 476/73 and WSL2
535/14 (passed/skipped), with the expected injected legacy Pi warning.

The Codex slow-subscriber peer now floods through actual child stdout;
the quiet session both completes a normal turn and, in a separate held-turn
case, preserves targeted `turn/interrupt` through saturation. Focused
Windows/WSL2 Python 3.11-3.13 tests passed. The full Python 3.13 suites
including this test passed at Windows 477/73 and WSL2 536/14
(passed/skipped), with the expected injected Pi warning. The matching
Windows/WSL2 artifact pair has wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`
and sdist SHA-256
`8d41b67f41baf8b8a45f28c58a74570e11f8ec84c2fe2701ba5cab78106bb3db`;
release/offline checks passed, but `publishable` remains false.

The Codex shared-history pressure case now emits 2,200 child-stdout frames,
exceeding the 2,048-item transient window: noisy replay expires explicitly,
while quiet replay and targeted interrupt survive. Focused tests passed on
Windows/WSL2 with Python 3.11-3.13. Full Python 3.13 suites passed at
Windows 478/73 and WSL2 537/14 (passed/skipped), with the expected injected
Pi warning. The current matching wheel/sdist SHA-256 are
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`
and `1ad6d9ea0c7aa74e429ed677145f963fda9e6bc6c519d6a770d7cb6cd12620b5`.
Strict Twine, clean-wheel consumers, development-mode release validation
and Windows offline wheel/sdist installation passed. This remains partial
TK-40: sustained real-provider and byte-pressure qualification is open.

K04/K10 fairness fix: global transient history eviction previously dropped
the oldest quiet event when several noisy Codex sessions together exhausted
the shared byte cap. It now evicts within the session holding the most bytes
or items and reports that session's replay gap explicitly. Unit tests prove
the prior failure; a six-noisy-session native stdout campaign crossed the
4 MiB history cap while quiet replay and targeted interrupt survived.
Focused Windows/WSL2 Python 3.11-3.13 tests passed. Full Python 3.13 suites
passed at Windows 481/73 and WSL2 540/14 (passed/skipped), with the expected
injected Pi warning. The matching wheel/sdist SHA-256 are
`360b0b02df671230dc4ede62a31b8bd801c36c64b4e3eb3c610320c31b11d562`
and `e60817cec8caf884f1d19e47fce006dc18a343460638598aa1b5b40d1ed758bc`.
Strict Twine, clean-wheel consumers, development-mode release validation
and Windows offline wheel/sdist installation passed. Real-provider TK-40
qualification remains open.

K04/K10 large-event fairness preflight: a new event larger than every
retained session footprint is no longer allowed to erase several small
replays under global byte pressure. Its own transient replay expires
explicitly before global eviction; live subscriber fanout remains separate.
The regression reproduced the old failure and passed on Windows/WSL2 Python
3.11-3.13. Full Python 3.13 suites passed at Windows 482/73 and WSL2 541/14
(passed/skipped), with the expected injected Pi warning. Current matching
wheel/sdist SHA-256 are
`43c78dfae685052830df647df3b7afdb64d318e322009ee4f0fc79bc6b251915`
and `8378660e9d38e94b8ad19b5df51f443a3895da4de5ffd217d18814884c58d7c9`.

Strict Twine, clean-wheel consumers, development release validation and
Windows offline wheel/sdist installation passed. TK-40 real-provider
qualification remains open.

K04/K10 live fanout follow-up: a large Codex event refused from transient
replay still reached its already registered subscriber, left quiet replays
intact and kept the native peer alive. Focused Windows/WSL2 Python 3.11-3.13
tests passed. The WSL2 Python 3.13 full suite passed at 542/14; Windows
passed at 483/73 on repeat after an initial unrelated Pi local-socket test
failure that passed alone. This transient is unrooted, not silently counted
as a clean first pass; twenty further isolated repeats of that Pi case
passed without reproducing it. Rebuilt wheel/sdist hashes remained
`43c78dfae685052830df647df3b7afdb64d318e322009ee4f0fc79bc6b251915`
and `8378660e9d38e94b8ad19b5df51f443a3895da4de5ffd217d18814884c58d7c9`.

K04/K10 bounded compaction update: explicit ACKed-event compaction now
rejects non-integral, boolean, nonpositive and >4,096-row batches at the
public facade and SQLite journal before deletion or host-journal delegation.
The default remains 128. Focused tests passed on Windows/WSL2 Python
3.11-3.13; full Python 3.13 suites passed at Windows 493/73 and WSL2
552/14 (passed/skipped), with the expected injected Pi warning. Matching
wheel/sdist SHA-256 are
`6a40a33ee9b2664c609066c80fadc5529da4d5eaf8c34e50589c11b5eeb7f514`
and `e996306abd7da5078e8ce8c2691592638e98e13385a9287d545396efa5896f5d`.
Strict Twine, clean-wheel consumers, development release validation and
Windows offline wheel/sdist installation passed. This does not establish a
hard WAL/filesystem bound. See
`plans/implementation/evidence/journal-compaction-batch-2026-09-26.md`.

K04/K10 durable session identity update: `runtime.open` now claims a
Server/executor/session ID atomically with journal admission. A new operation
cannot reuse it after safe failure, close or restart; an exact duplicate
operation still returns its prior receipt. Migration backfills prior journal
history, concurrent SQLite connections admit one claim, and injected
operation-insert failure rolls the claim back. The Journal-port conformance
kit now rejects a host adapter that ignores `claim_session`. Focused
Windows/WSL2 Python 3.11-3.13 tests passed; full Python 3.13 suites passed
at Windows 499/73 and WSL2 558/14 (passed/skipped), with the expected
injected Pi warning. Matching wheel/sdist SHA-256 are
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`
and `529886b5f79907d746270db8a3e55f10b2665f63944f5b3c81e717345de7fc78`.
Strict Twine, clean-wheel consumers, development release validation and
Windows offline wheel/sdist installation passed. Persisted physical process
ownership, lease and full reconnect fencing remain open. See
`plans/implementation/evidence/session-claim-fence-2026-09-26.md`.

The session-claim race now also runs across two independent Python processes
on Windows/WSL2 Python 3.11-3.13. One claim and one operation row survive;
the loser gets `SESSION_CONFLICT`. Final Python 3.13 suites passed at Windows
500/73 and WSL2 559/14 (passed/skipped), with the expected injected Pi
warning. The wheel SHA-256 stayed
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`;
the Windows/WSL2-matching sdist SHA-256 is
`1b0a6ddedf0893ad5c934da2c8a6b00b7731b100dc61a2df63941314a75584bc`.
Strict Twine, development release validation and Windows offline wheel/sdist
installation passed. Physical ownership/takeover qualification remains open.

K08 attach update: selected-PID registry identity and discovery filenames are
checked, symlink listings are excluded, and the key/procStart reuse guard
fails closed on unreadable or missing evidence. The managed factory still
rejects attach; public scoped attach lifecycle and real Claude qualification
are open. Details are in
`plans/implementation/evidence/attach-identity-guard-2026-09-25.md`.

K11 consumer update: a source-contained, application-free embedded/remote
smoke runs in separate isolated processes against the installed wheel; real
Server and Connector builds remain untested. Details are in
`plans/implementation/evidence/consumer-smoke-2026-09-25.md`.

K11 release update: the local candidate passes strict Twine metadata checks
and the Core-owned artifact validator in development mode. A protected manual
publication path is staged but has not been run or configured on GitHub/PyPI.
Details and required external gates are in
`plans/implementation/evidence/release-workflow-2026-09-25.md`.

TK-42 offline-package update: separate wheel/sdist installs from a locally
prepared dependency wheelhouse passed on Windows and WSL2 for Python 3.11,
3.12 and 3.13 with index/cache access disabled. CI stages the same check, but
this does not establish a physically isolated machine or hosted matrix result.
Details are in `plans/implementation/evidence/offline-package-2026-09-26.md`.

K11.3 documentation update: public guides under `docs/` describe the actual
exported API, lifecycle/uncertainty, exact development revision, adapter
provenance and security limits. They are bundled in the sdist and checked
against current exports/registry/link targets. Real-provider version ranges
and migration of live application consumers are still unqualified.

K04 storage update: a fresh noncritical admission now makes one bounded
ACKed-only compaction and non-waiting checkpoint attempt at the physical
headroom threshold. It still denies admission if pressure remains; background
maintenance and a hard filesystem quota remain pending. Details are in
`plans/implementation/evidence/journal-admission-recovery-2026-09-25.md`.

The bounded ACK-only physical recovery pass now also precedes new normal
event writes through either journal API. Synthetic Windows/WSL2 tests confirm
that only ACKed rows are reclaimed and non-ACKed events remain replayable.
The same bounded pass now also triggers on normal event logical byte/row
pressure, prioritizing the affected session and Server/executor; targeted
Windows/WSL2 tests pass. A hard WAL bound and sustained campaigns remain open.

K04/K10 session fairness update: the journal now accounts event rows/bytes
per session as well as globally and per Server/executor. A saturated session
cannot consume another session's normal budget, while finite critical reserve
remains available. Concurrent writers, upgrade reconstruction and ACKed
compaction have targeted Windows/WSL2 tests. This is only partial TK-40;
native slow-consumer and host-wide campaigns remain open. Details are in
`plans/implementation/evidence/journal-session-fairness-2026-09-26.md`.

The runtime's optional event-sink callback is now delivered from durable
journal replay on a per-session task, so a slow notification consumer does
not block native event draining; a failed callback is retried on the next
append. Synthetic stall/retry and urgent-control tests pass. Real provider
slow-consumer and sustained saturation qualification remain open.

The sink worker now handles an append racing with callback failure by
retrying from its durable cursor once, without spinning when no new event
arrives. It also notifies a durable pump-fault event. Targeted Windows/WSL2
tests pass; sink notification remains best effort and hosts must replay.

The same fairness boundary now applies to durable operation rows: a session
has a configurable normal/critical split, and the counter survives restart or
is reconstructed on upgrade. Receipts are retained, so the per-session cap is
not automatically reclaimed. Global pressure and host-wide fairness remain
open; this does not close TK-40.

Durable operation rows now also have a configurable Server/executor cap and
critical reserve, reconstructed on upgrade and enforced atomically across
concurrent SQLite connections. A noisy Server with many sessions no longer
spends every global operation slot; real multi-host fairness remains open.

The global operation-row limit now uses a transactional singleton counter
instead of `COUNT(*)` on every admission. It is reconstructed on upgrade;
targeted Windows/WSL2 tests verify reserve, duplicates and concurrent
last-slot admission. Long-lived receipt retention and real host-scale profiling
remain open.

A Core-owned temporary-journal campaign admitted 100,000 synthetic
operations on Windows and WSL2, exercised global normal/critical reserve,
duplicate lookup at saturation and reopen. It completed in 80.304 s and
60.527 s respectively, without observed batch-time growth. This is not the
100,000-agent Server scenario or a concurrent-host fairness gate. Evidence:
`plans/implementation/evidence/journal-100k-scale-2026-09-26.md`.

Four independent Core-only processes also contested one SQLite journal.
Targeted Windows/WSL2 × Python 3.11–3.13 tests verify that a noisy Server
cannot consume a quiet Server's reserved normal/critical capacity and that
four Server namespaces cannot oversubscribe the final three global slots.
This is process-level SQLite evidence, not production multi-host parity or
TK-40/TK-41/J08 closure. See
`plans/implementation/evidence/journal-multiprocess-fairness-2026-09-26.md`.

The expanded process campaign also races critical writers across global,
Server and session hard caps. Three targeted tests passed on Windows/WSL2 ×
Python 3.11–3.13. The stable Python 3.13 full suites passed at Windows
447/73 and WSL2 506/14 (passed/skipped). The sdist now includes its
process-test fixtures, and local Windows/WSL2 builds matched byte-for-byte;
the development release remains non-publishable.

K04 shutdown observation is now finite for held native sends, closes and opens;
the deadline reports `unknown` while retaining owned slots, and a late open
starts cleanup. A known active turn now receives a distinct drain window and
a journaled technical interrupt attempt, exercised with synthetic backends.
An independent force request now reaches only Core-owned managed process
backends after the windows, with local peer tests on Windows/WSL2 and no early
slot release. Explicit force tests also verify a descendant dies with its
leader on Windows and Linux. The remaining K04 shutdown gate is real-provider and full-OS
drain/interrupt/force qualification. The table's broader
restart and host-wide ownership gates remain open.
The copied native bridge also permits containment retry after a failed or
unobserved close and never infers `forced` solely from observed stop.
K00's wheel audit now rejects dynamic sibling imports, common `sys.path` mutator calls
and file-based module loading; clean-wheel installation/import passed on
Windows and WSL2 after removing stale application-namespace references from
the copied adapter documentation. This is not a real-provider qualification.

`pytest -q`: 420 passed, 73 skipped on each local Windows/Python 3.11,
3.12 and 3.13 environment; Ubuntu WSL2/Python 3.11, 3.12 and 3.13 against
`PYTHONPATH=src`: 479 passed, 14 skipped in each,
one expected warning from a legacy Pi fault-injection test.
A clean virtual environment
installed the local wheel and its pinned JCS dependency and imported all four adapters and contract
resources. This is local unit/contract and limited Windows/WSL2 process
evidence; the full provider, OS-matrix and multi-host gates remain `NOT_RUN`.
No PyPI publication or remote repository was created.

The `0.1.0.dev0` artifact is a development build. Its bundle manifest is
explicitly marked `development-partial`; it is not a completed K01 contract
bundle and is not yet normative for consumers. The generator is included in
the sdist, and bundle parity can be checked with
`python contracts/generate.py --check`. Details are in
`plans/implementation/evidence/contract-bundle-2026-09-25.md` and
`plans/implementation/evidence/jcs-2026-09-25.md`.
Bounded NXL frame validation is recorded in
`plans/implementation/evidence/frame-codec-2026-09-25.md`.
The first pure NXL receipt producer/consumer projection is in
`plans/implementation/evidence/receipt-reducer-2026-09-25.md`.
The bounded NXL event batch/ACK projection is in
`plans/implementation/evidence/event-reducer-2026-09-25.md`.
The NXL inventory snapshot/delta projection is in
`plans/implementation/evidence/inventory-reducer-2026-09-25.md`.
The NXL lease request/grant projection and unresolved correlation convention
are in `plans/implementation/evidence/lease-reducer-2026-09-25.md`.
The pinned offline consumer bundle verification is in
`plans/implementation/evidence/consumer-conformance-2026-09-25.md`.

Direct HTTP origin/reachability validation and pure JSON config planning are
recorded in `plans/implementation/evidence/config-plan-2026-09-25.md`.
Harness-specific direct HTTP templates are in
`plans/implementation/evidence/harness-http-templates-2026-09-25.md`.
Ownership-checked Codex TOML planning/apply is in
`plans/implementation/evidence/codex-toml-merge-2026-09-25.md`.
The restricted capability environment path is in
`plans/implementation/evidence/mcp-capability-env-2026-09-25.md`.
The typed native-action port is in
`plans/implementation/evidence/native-action-bridge-2026-09-25.md`.
The Core-owned native-event redaction boundary is in
`plans/implementation/evidence/native-redaction-2026-09-25.md`.
The Pi extension artifact and synthetic test limits are in
`plans/implementation/evidence/pi-extension-2026-09-25.md`.
The metadata-first adapter registry is in
`plans/implementation/evidence/native-registry-2026-09-25.md`.
The read-only source-to-Core SHA and dependency inventory is in
`plans/implementation/evidence/extraction-provenance-2026-09-25.md`.
Linux/POSIX wheel, attach and guardian observations are in
`plans/implementation/evidence/linux-wsl2-2026-09-25.md`.
Local JSON apply/removal evidence and security limits are in
`plans/implementation/evidence/config-persistence-2026-09-25.md`.
Journal ACK/compaction evidence is in
`plans/implementation/evidence/journal-compaction-2026-09-25.md`.
The reusable Journal-port conformance trace and admission correction are in
`plans/implementation/evidence/journal-conformance-2026-09-25.md`.
Urgent-control scheduling and close serialization evidence is in
`plans/implementation/evidence/runtime-control-concurrency-2026-09-25.md`.
Core event-pump startup ordering and immediate-failure evidence is in
`plans/implementation/evidence/runtime-reader-startup-2026-09-25.md`.
Concurrent-open capacity and its live-process limit are in
`plans/implementation/evidence/runtime-open-capacity-2026-09-25.md`.
The per-runtime owned-session budget, retained unknowns and safe prelaunch
rejection are in `plans/implementation/evidence/runtime-owned-capacity-2026-09-25.md`.
Bounded shutdown observation, independent closes and late-open cleanup are in
`plans/implementation/evidence/runtime-shutdown-budget-2026-09-25.md`.
Copied-bridge close retry and honest stop attribution are in
`plans/implementation/evidence/native-close-retry-2026-09-25.md`.
The synthetic drain/interrupt phase and qualification limits are in
`plans/implementation/evidence/runtime-shutdown-phases-2026-09-25.md`.
The managed-tree force request and retained-effect boundary are in
`plans/implementation/evidence/runtime-force-containment-2026-09-25.md`.
The unexecuted hosted CI matrix and its local checks are in
`plans/implementation/evidence/ci-workflow-2026-09-25.md`.
The isolated-wheel runtime dependency inventory and license-review limits are
in `plans/implementation/evidence/runtime-sbom-2026-09-25.md`.
Local wheel/sdist archive repeatability and its limits are in
`plans/implementation/evidence/reproducible-build-2026-09-25.md`.
Abrupt journal-process crash cuts are in
`plans/implementation/evidence/journal-crash-2026-09-25.md`.
Kernel effect-boundary crash cuts are in
`plans/implementation/evidence/kernel-effect-crash-2026-09-25.md`.
Physical storage pressure and checkpoint evidence is in
`plans/implementation/evidence/journal-storage-2026-09-25.md`.
SQLite page-exhaustion rollback and recovery evidence is in
`plans/implementation/evidence/journal-disk-full-2026-09-25.md`.
Selected native version/architecture probing is in
`plans/implementation/evidence/claude-probe-2026-09-25.md`.
Selected Pi version observation and its unqualified status are in
`plans/implementation/evidence/pi-probe-2026-09-25.md`.
Selected native Codex version observation and its unqualified status are in
`plans/implementation/evidence/codex-probe-2026-09-25.md`.
The native no-turn Codex app-server handshake and its qualification limits are
in `plans/implementation/evidence/codex-handshake-2026-09-25.md`.
The version-pinned generated Codex protocol bundle and shape checks are in
`plans/implementation/evidence/codex-schema-2026-09-25.md`.
The scoped Codex resume path, native no-rollout observation and remaining
qualification limits are in `plans/implementation/evidence/codex-resume-2026-09-25.md`.
Native pre-write refusal classification and durable safe/unknown tests are in
`plans/implementation/evidence/native-prewrite-failure-2026-09-25.md`.
Safe requesting-phase control rejection is in
`plans/implementation/evidence/claude-control-2026-09-25.md`.
Conditional native-turn targeting and Codex-only public steer are in
`plans/implementation/evidence/targeted-control-2026-09-25.md`.

The complete TK/J acceptance matrix is in `matrix.md`; every full scenario
remains `NOT_RUN` until its prescribed environment and scope are exercised.

K04 recovery update: the Core journal now pages durable session-ID claims for
one Server/executor under a fixed scan watermark, allowing a host to discover
IDs after restart without asserting that their processes remain active. The
RuntimeCore/Journal ports and reusable conformance kit cover this operation.
Windows/WSL2 Python 3.11-3.13 focused and Python 3.13 full suites passed.
Physical ownership, takeover, and actual Server adapter parity remain open;
see `plans/implementation/evidence/session-claim-inventory-2026-09-26.md`.

K04 reconciliation update: in-process `reconcile` now enforces the bundled
NXL per-list ID count, length and uniqueness limits before journal I/O.
Focused Windows/WSL2 Python 3.11–3.13 and full Python 3.13 suites passed;
the real Server host adapter remains unverified. See
`plans/implementation/evidence/reconcile-request-bounds-2026-09-26.md`.

K04/TK-41 port update: the reusable Journal conformance kit now includes
close/reopen continuity for the operation effect marker, session claim,
event sequence/replay and ACK. The SQLite reference passes and an ephemeral
adapter is detected. The actual Server host adapter and process-crash gate
remain untested; see
`plans/implementation/evidence/journal-reopen-conformance-2026-09-26.md`.

K11/TK-42 packaging update: the current exact wheel/sdist pair now passes
offline installation and bundled-resource checks on all six local
Windows/WSL2 × Python 3.11–3.13 combinations. Hosted CI, native non-WSL
Linux and real consumers remain unverified; see
`plans/implementation/evidence/offline-six-env-2026-09-26.md`.

K04/TK-17 birth-record update: Core-owned Windows/Linux containers now yield
OS birth tokens, persisted immutably under the original open session claim.
The record survives journal reopen while `inspect` remains unknown without
a live binding. Journal-write failure cannot publish a successful open.
This is diagnostic history, not PID-control or takeover authority; see
`plans/implementation/evidence/process-birth-record-2026-09-26.md`.

K04/TK-17 integration update: a synthetic connector launched through the
Core-owned copied-adapter factory now creates a real contained child and
proves that public `runtime.open` persists its actual OS birth identity.
This passed on Windows/WSL2 Python 3.11–3.13; real-provider qualification
and post-restart physical ownership are still open.

K04/TK-17 observation update: the Core can compare a persisted birth with a
read-only OS observation, distinguishing a matching live PID, changed birth,
stopped/not-observed PID and inconclusive evidence without changing ownership
or granting PID-control authority. Windows/WSL2 Python 3.11–3.13 focused
tests and full Python 3.13 suites passed; see
`plans/implementation/evidence/process-birth-observation-2026-09-26.md`.

K04/TK-17 birth-journal crash update: abrupt exit before a birth write, during
its uncommitted INSERT, or after its commit leaves respectively no record,
no record, or the exact record on reopen. The original possible-effect
receipt prevents duplicate admission from becoming a new execution. The
11-case journal crash suite passed on Windows/WSL2 Python 3.11–3.13. A
separate real contained-child cut now kills its Core owner after spawn but
before birth registration; Windows handles/Linux pidfds confirm owner-death
reaping while the journal keeps the possible-effect receipt and no fabricated
birth record. It passed on the same six local combinations; full Python 3.13
suites passed at Windows 544/73 and WSL2 603/14 (passed/skipped). The cut
does not cover a crash inside OS spawn/containment establishment; see
`plans/implementation/evidence/process-birth-journal-crash-2026-09-26.md`.

K04/J23 reconnect update: in-process lease renewal/revocation CAS now waits
under both per-session command locks for older normal/control native sends.
The bounded wait returns `RECONNECT_BUSY` or `REVOKE_BUSY` without applying
the lease update if a send remains pending. Focused Windows/WSL2 × Python
3.11–3.13 tests and full Python 3.13 suites (Windows 547/73, WSL2 606/14)
passed. Durable cross-instance generations, host reconnect parity and
physical takeover remain open; see
`plans/implementation/evidence/reconnect-generation-fence-2026-09-26.md`.

K04/J23 opening-generation update: `runtime.open` now persists its initial
connection and session-owner generations atomically with the session claim
and operation receipt. Paged claim history exposes those immutable fields;
legacy claims remain unknown. Rollback, process contention, reopen, abrupt
crash and host-Journal conformance cases passed. Focused Windows/WSL2 ×
Python 3.11–3.13 and full Python 3.13 suites (Windows 554/73, WSL2 613/14)
passed. This is historical opening evidence, not durable current-owner CAS or
takeover authority; see
`plans/implementation/evidence/opening-generations-2026-09-26.md`.

K04 capacity update: managed opens now reserve a transactional slot shared by
all Core instances using one SQLite journal, with a durable default cap of
eight and policy-drift rejection. Safe prelaunch refusal or observed stop
releases it; an uncertain open/close and abrupt owner death retain it. A
three-process race for two slots and six local Windows/WSL2 × Python
3.11–3.13 focused suites passed. Concurrent SQLite WAL initialization now
retries transient busy/locked errors within five seconds; the originally
failing WSL2/Python 3.11 race passed ten subsequent repetitions. Separate
journal files still need a common installation ledger; see
`plans/implementation/evidence/shared-journal-owned-slots-2026-09-26.md`.
Full Python 3.13 suites passed Windows 562/73 and WSL2 621/14
(passed/skipped); the current matching wheel/sdist pair passed strict Twine,
clean-wheel consumers, development release validation and six-environment
offline installation. Publication remains disallowed.

K04 installation capacity update: Core now offers a separate, injectable
`SQLiteOwnedSlotLedger` so distinct executor journals can share one durable
eight-slot installation budget when the trusted host opens the same absolute
local ledger path. Two runtime journals and a three-process race demonstrated
cross-journal/cross-process admission; ambiguous effects stay reserved across
reopen. The reusable slot-ledger conformance/restart kit covers alternative
host adapters. Focused Windows/WSL2 × Python 3.11–3.13 and full Python 3.13
suites passed (Windows 569/73, WSL2 628/14). Real host path wiring and crash
reconciliation remain open; see
`plans/implementation/evidence/installation-slot-ledger-2026-09-26.md`.
The matching normalized Windows/WSL2 wheel and sdist passed strict Twine,
clean-wheel consumers, development release validation and six-environment
offline installation; publication remains disallowed.

K04 recovery inventory update: both Core-owned slot-ledger variants now
offer bounded paged inspection of unresolved reservations, including the
original open operation ID. Scans fence new inserts by high-water row ID;
they do not prove liveness or authorize release. The reusable port kit and
crash-race tests cover this read-only surface. Real host reconciliation
remains open; see
`plans/implementation/evidence/owned-slot-inventory-2026-09-26.md`.
Focused tests passed in all six local Windows/WSL2 × Python 3.11–3.13
environments; full Python 3.13 suites passed Windows 570/73 and WSL2 629/14
(passed/skipped). Matching normalized artifacts passed strict Twine,
clean-wheel consumers and six-environment offline installation. The
development version remains unpublishable.

K04/K10 finite-time update: malformed or non-finite host lease deadlines,
overflowing lease+grace windows, constructor timing sums and shutdown phase
budgets now fail before native admission or drain. The runtime/docs focused
suite passed 60 tests in each local Windows/WSL2 × Python 3.11–3.13
environment; see
`plans/implementation/evidence/finite-lease-shutdown-2026-09-26.md`.
Full Python 3.13 suites passed Windows 572/73 and WSL2 631/14
(passed/skipped). The matching normalized artifact pair passed strict Twine,
clean-wheel consumers and six-environment offline installation; publication
remains disallowed.

K05/K07 HITL validation update: full Python 3.13 suites passed Windows
583/73 and WSL2 642/14 (passed/skipped). Normalized Windows/WSL2 wheel
and sdist hashes matched; strict Twine, clean-wheel consumers and offline
wheel/sdist installs across Python 3.11–3.13 on both OSes passed. The
development artifacts remain non-publishable. See
`plans/implementation/evidence/native-approval-core-seam-2026-09-26.md`.

K05/K07 durable-request fence: a native decision now requires an exact request
event committed by the Core journal for the live session, not merely a
caller-supplied request projection. Successful/uncertain replies and terminal
turn events remove the process-local pending entry; the copied adapter still
checks its own original live request before writing. Focused runtime/bridge
tests pass 89 cases in each local Windows/WSL2 × Python 3.11–3.13
environment. Full Python 3.13 suites passed Windows 584/73 and WSL2 643/14
(passed/skipped); matching normalized artifacts passed strict Twine,
clean-wheel and six-environment offline installation. Host-side durable
pending-request CAS remains open.

K10.3 HITL hostile-input update: `decide_native_approval` now performs
bounded JSON structure checks before canonicalization/copy, with a 64-level
ceiling and exact 16 KiB post-canonical ceiling. It rejects huge, cyclic,
deep, non-JSON and non-finite answer/request trees before journal admission.
Focused runtime/bridge/docs tests passed 90 cases in each local
Windows/WSL2 × Python 3.11–3.13 environment; broader TK-39 fuzz and
real-provider campaigns remain open. Full Python 3.13 suites passed Windows
585/73 and WSL2 644/14 (passed/skipped); normalized artifacts matched across
Windows/WSL2 and passed strict Twine, clean-wheel consumer and six-environment
offline installation. Development publication remains disallowed.

K05/K07 HITL seam update: Core now exposes a typed, authorized and journaled
`decide_native_approval` operation for pending native approvals or input.
Copied Codex/Claude response paths reject method/tool spoofing, opt-in is off
by default, and operator answer content stays out of the technical journal.
A contained Codex peer demonstrated both approval denial and input answer,
including late-reply refusal. Focused runtime/bridge/docs tests passed 88
cases across local Windows/WSL2 × Python 3.11–3.13. Real provider and host
decision-routing qualification remain open; see
`plans/implementation/evidence/native-approval-core-seam-2026-09-26.md`.

K05/K04 turn-correlation update: the Core-owned Codex bridge now refuses
old/missing native terminal IDs instead of crediting them to a newer submit;
recent completed IDs also fence replayed starts. A runtime/journal test
keeps the newer receipt possible-effect and unsettled after a stale terminal.
Focused adapter/docs suites passed 24 tests across all six local
Windows/WSL2 × Python 3.11–3.13 combinations. Real provider ordering and
arbitrary-age replay remain unqualified; see
`plans/implementation/evidence/codex-terminal-correlation-2026-09-26.md`.
Full Python 3.13 suites passed Windows 576/73 and WSL2 635/14
(passed/skipped). Matching normalized artifacts passed strict Twine,
clean-wheel consumers and six-environment offline installation; publication
remains disallowed.
