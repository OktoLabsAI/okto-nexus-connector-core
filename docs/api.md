# Core API (`0.2.10.dev0`)

This is the development API of the independent `nexus-connector-core` wheel (correction revision C1).
The trusted host supplies authority, selected binaries, workspace roots,
credentials and canonical application state. Core does not import Nexus Server
or Connector code. The supported top-level exports are listed below; native
adapter modules and `CopiedAdapterFactory` are not a public host API.

| Export | Use |
| --- | --- |
| `RuntimeCore`, `LocalRuntimeCore`, `create_runtime` | Async port, local implementation and the supported composition factory. `create_runtime(journal=…, environment=…, candidates=…, workspace_roots=…, …)` builds the real runtime from typed host inputs (trusted callbacks for Codex client identity/resume/Pi native action, budgets, optional installation ledger, clock and event sink); hosts never import the private adapter bridge. A `native_factory` parameter exists for contract-level smokes with fakes. |
| `ExecutionContext` | Host-issued server/executor/binding/agent/workspace identity, revisions, generations, monotonic lease deadline and allowed actions. Never derive it from a peer payload. |
| `RuntimeCatalog`, `RuntimeDescriptor`, `get_runtime_catalog`, `CATALOG_FORMAT_VERSION` | Single-source runtime catalog (C9): enumerate what this Core knows - adapter IDs, family, connection mode, implementation platforms, support status (`claude_attach` = `registered_unqualified`, never READY by existing) - cheap, sync, no native provider modules, no spawn/journal/credentials. `DiscoveryRequest(adapter_ids=None)` asks the catalog which adapters admit discovery; availability/eligibility are separate concepts (local inventory + Server-side binding policy). |
| `installation_ref`, `resolve_installation`, `INSTALLATION_REF_SCHEME`, `REF_NOT_FOUND`, `REF_AMBIGUOUS` | Installation identity (C11): `candidate_ref` in the projection is now the opaque ref of the SELECTABLE LOCAL INSTALLATION (`nexus-install-v1:<sha256>` over the canonical executable + launch script) - byte-identical copies in distinct locations are TWO installations (distinct refs, SAME build identity). `resolve_installation(inventory, adapter_id, candidate_ref)` resolves a selection to EXACTLY one `InstallationCandidate` on the producing host: zero matches raise typed `INSTALLATION_REF_NOT_FOUND` (missing/stale/foreign executor), more than one distinct match raises typed `INSTALLATION_REF_AMBIGUOUS` (reselection - never an order-based pick). Legacy v1 refs (content fingerprints) still resolve when the inventory proves exactly one target; identical copies are ambiguous by construction. Alias policy: PATH entries/symlinks resolving to the same canonical target are ONE installation (discovery dedups by ref). Move/rename changes the ref (old ref = stale, reselect); a content update keeps the ref but prepare/open keep refusing drift. Refs know nothing of authorization - the agent's policy stays in the Server. |
| `evaluate_runtime_availability`, `AvailabilityReport`, `CandidateAvailability`, `AVAILABILITY_FORMAT_VERSION` | Per-candidate TECHNICAL availability (C10): assess an `Inventory` (from `runtime.discover`) passively - the registry's platform support, `compatibility`'s exact-build qualification and the containment preflight of the EXECUTING host (never the rendering UI's). States: `NOT_INSTALLED`, `UNSUPPORTED_PLATFORM`, `NOT_PROBED`, `UNQUALIFIED_BUILD`, `CONTAINMENT_UNAVAILABLE`, `PREPARATION_REQUIRED`, `READY_FOR_RUNTIME` with stable `reasons` codes; an absent probe stays inconclusive (never READY by omission); two builds of one family never merge (`candidate_ref` = the producing host's inventory fingerprint; the executing host resolves it at prepare time, which revalidates). `AvailabilityReport.to_dict()` is the explicit versioned JSON-safe remote projection (no paths/modules/credentials; NXL frames unchanged - Connector/Server transmit it on their own versioned API). `READY_FOR_RUNTIME` is TECHNICAL ONLY - the agent's authorization stays in the Nexus Server. |
| `DiscoveryRequest`, `Inventory`, `InstallationCandidate` | Discover or pass explicitly selected local native candidates; discovery is not qualification. |
| `LaunchIntent`, `PreparedLaunch`, `OpenOperation` | Prepare a selected managed launch and open a session. `open` revalidates binary/profile/root before native effect. |
| `TurnOperation`, `ControlOperation`, `CloseOperation` | Submit text, interrupt/steer a targeted turn, or close an owned session. Steer targeting is adapter-specific (see below). Use a new operation ID for each new intent. |
| `CodexResumeGrant` | Public trusted-host resume contract for binding one stored Codex thread to one open (C2/R09). Construct from this package; the bridge validates the exact type and every binding field. |
| `NativeApprovalOperation` | Host-authorized response to one pending Codex/Claude native approval or input request. The host passes the redacted event's `native_approval` projection; the adapter checks it against its original in-memory request. |
| `Operation`, `OperationKey`, `OperationReceipt`, `intent_hash`, `submit_frame_intent_hash` | Semantic intent identity and namespace-scoped durable receipt. Reuse an operation ID only for the identical intent. |
| `SessionKey`, `RuntimeSnapshot`, `ReconcileRequest`, `ReconcileReport` | Namespace-scoped inspection and recovery queries. A missing process-local handle yields unknown ownership, not proof of stop. |
| `ClaimedSession`, `SessionClaimPage` | Paged durable session-ID history with the original open operation ID and, for new Core opens, opening connection/owner generations. These are claims, not active-process or lease observations. |
| `SessionLeaseState` | Durable last-known lease fence for one claimed session, written atomically with the claim and advanced by `renew_lease`/`revoke_lease` through journal CAS. Fence evidence for host reconciliation — not process liveness, not a lease deadline, not takeover authority. |
| `AttachTarget`, `AttachPolicy` | Public evidence/policy types for the future external attach mode: the host selects exactly one target with verifiable identity and approves it; the policy fixes detach-only semantics (never kill the external tree). Preparing an attach launch still fails `CAPABILITY_UNSUPPORTED` prescriptively until the substrate is qualified — no flag enables it. |
| `ProcessBirthEvidence`, `ProcessBirthRecord` | Historical OS birth identity for a Core-owned process container. PID/token are diagnostic evidence, never authority to signal or reattach after restart. |
| `ProcessBirthObservation` | One read-only, transient comparison of a stored birth to the current OS PID; it does not grant ownership. |
| `RuntimeEvent`, `EventCursor` | Durable technical event stream; cursor includes server, executor, session and stream epoch. |
| `StorageStatus` | SQLite database/WAL/SHM observation. Logical quotas are not a hard filesystem quota. |
| `OwnedSlotLedger`, `SQLiteOwnedSlotLedger` | Optional installation-wide owned-slot port and Core-owned SQLite implementation. Every runtime in that installation must receive handles to the same absolute ledger path. |
| `OwnedSlotReservation`, `OwnedSlotPage` | Bounded read-only inventory of unresolved reservations and their original open operation IDs; it is not process-liveness or release authority. |
| `ShutdownPolicy`, `ShutdownReport` | Bounded drain/interrupt observation and per-session outcome. `unknown` retains ownership. |
| `CoreError` | Typed failure with `code`, `stage`, `possible_effect`, `retry_safe` and optional `operation_id`. C3/S07: `code` is a stable machine-readable enum; human diagnostics (redacted by the raiser) travel in the separate `message` field (`str(exc)` shows the message). |
| `CONTRACT_REVISION` | Exact NXL revision required by development negotiation; see [compatibility](compatibility.md). |

`LocalRuntimeCore` implements `discover`, `prepare`, `open`, `submit`,
`control`, `decide_native_approval`, `events`, `acknowledge_events`, `compact_events`, `storage_status`,
`checkpoint_wal`, `inspect`, `claimed_sessions`, `process_birth`,
`observe_process_birth`, `persisted_lease`, `reconcile`, `close`, `shutdown`, `renew_lease` and
`revoke_lease` as defined in `RuntimeCore`. `events` is an async iterator; the
other public operations above are awaited. `acknowledge_events` is for a
trusted host **after** its Server durable-ingress ACK, not on network receipt.
The local constructor's `reconnect_fence_seconds` bounds the wait for pending
session native sends before `renew_lease`/`revoke_lease` can report a
successful generation or revocation update; a busy error leaves that update
unapplied.
`decide_native_approval` requires `approval.decide` or `input.provide` in the
host-issued `ExecutionContext` and in the active binding. The Core first
requires an exact matching native request event that its own journal has
committed for this live session. A fabricated, edited, already answered or
terminal-turn request fails before operation admission. Its intent is
durable before the native reply; a successful write returns `SUBMITTED`, not
proof that the provider acted. Only the response digest enters the journal,
not operator answer content. Stale requests fail before write; a write error
remains uncertain. Request and answer JSON have a 16 KiB encoded ceiling and
a 64-level structural ceiling. Grossly oversized, cyclic or non-JSON input is
refused before canonicalization; exact encoded-size excess is refused before
journal admission.
`CopiedAdapterFactory(native_approvals_enabled=True)` is
an explicit host opt-in, off by default, and does not by itself qualify a
provider build or grant an approval decision.
The opt-in also requires both `approval.decide` and `input.provide` in the
launch context; otherwise launch refuses before resolving credentials.
`compact_events(max_rows=...)` accepts only an integer from 1 to 4,096
(default 128); invalid batches fail before calling the journal port.
`turn.steer` targeting is adapter-specific. The Codex app-server adapter
requires `expected_turn_id` naming the active native turn and refuses a
steer without one before admission. The Pi RPC adapter has no native turn
ID on the wire: its steer is admitted only with `expected_turn_id=None`,
targets the agent run Core observed starting (`agent_start`) for the active
submit, and refuses before admission when a native turn ID is supplied.
The copied-adapter bridge refuses an ID-less Pi steer before the native
write with a retry-safe `STALE_TURN` when no submit is active or its agent
run has not been observed starting; delivery then follows Pi's native
next-turn-boundary steering queue (`queue_update`), not immediate
injection, and the steered content stays part of the same active turn. A
Pi follow-up after `agent_settled` is a new `turn.submit`. Every steer
still requires `turn.steer` in the host-issued `ExecutionContext` and in
the active binding. This contract is exercised against contained peers
and the public runtime; real-provider steer/queue behavior remains
unqualified.
`runtime.open` atomically claims its session ID in the journal namespace;
host journal adapters must implement the `claim_session` admission flag and
atomically retain the supplied opening generations with that claim. Legacy
claims without this evidence report `None`, never a guessed generation.
When the opening admission also supplies the authorization/configuration
revisions, the claim seeds a durable `session_lease_state` row.
`renew_lease` and `revoke_lease` advance that row through journal CAS before
the in-memory generation changes: a second Core instance sharing the journal,
or a host-side CAS, makes an older renewal fail `STALE_GENERATION` without
ever becoming active, and a revocation committed durably can never be
un-revoked. A legacy claim without lease evidence fails renewal with
`SESSION_UNKNOWN` rather than being seeded from memory. `persisted_lease`
reads the last durable fence for host reconciliation after restart; it is
evidence, not liveness or takeover authority. Host journal adapters must
implement `cas_session_lease`/`get_session_lease`.
For managed launches, the Journal port must also implement
`reserve_owned_slot`/`release_owned_slot`; a reservation is acquired after
possible-effect admission but before native launch and is retained on an
uncertain outcome. `JournalLimits.max_owned_slots` defaults to eight for one
shared SQLite file. For distinct technical journals, construct separate
`SQLiteOwnedSlotLedger` handles over one installation-owned absolute local
path and pass each as `LocalRuntimeCore(owned_slot_ledger=...)`; otherwise
there is no cross-journal cap. The host owns ledger lifetime and must not
delete, replace, or reinterpret unresolved reservations as free slots.
The host may call `owned_slot_page(after_rowid=..., high_water_rowid=...,
limit=...)` on its ledger to inspect unresolved reservations across all
namespaces. The first page fixes a high-water row ID; pass it and
`next_after_rowid` to subsequent pages. `limit` is 1–4096 (default 128).
Concurrent release can remove a row between pages, so this is a bounded
inventory, not an atomic point-in-time snapshot or proof of physical stop.
`SESSION_CONFLICT` on a new operation means the session ID has already been
used, even if the prior open was safely refused.
For Core-owned child containers, `open` also stores immutable
`ProcessBirthEvidence` under that claim before returning success. The
`process_birth(SessionKey)` query returns the historical `ProcessBirthRecord`
or `None`; its PID/token do not grant process-control authority. A host Journal
adapter must implement `record_process_birth` and `get_process_birth`.
`observe_process_birth` returns `UNRECORDED`, `MATCHING_LIVE`,
`DIFFERENT_BIRTH`, `NOT_RUNNING`, `NOT_OBSERVED`, or `UNKNOWN` from a
read-only OS check. Even `MATCHING_LIVE` is a transient observation, not a
lease or permission to signal the PID.
`reconcile` accepts at most 256 distinct operation IDs and 256 distinct
session IDs per call, each 1–160 characters, matching the bundled NXL
`reconcile.request` frame. Invalid requests fail before journal lookup; hosts
should batch larger recovery scans.

Host journal adapters should run both
`nexus_connector_core.testing.run_journal_conformance(adapter)` and
`run_journal_restart_conformance(open_journal)`. The latter accepts a callable
returning an async context manager: each call must open the same private
backing store and close its adapter on exit. It checks operation/effect-marker,
session-claim, event-sequence and ACK continuity across two reopen cuts. It
does not simulate an OS crash or establish native process ownership.
Alternative installation ledgers should also pass
`run_owned_slot_conformance(ledger, max_slots=...)` and
`run_owned_slot_restart_conformance(open_ledger)` on a private empty store.

Minimal use with an injected test/native factory is exercised by
`tools/consumer_smoke.py` for separate embedded and remote consumer shapes.
Real Server/Connector integration and native provider qualification remain
open. Consumers should verify the installed contract bundle using
`python -m nexus_connector_core.conformance` with an expected manifest hash;
the current bundle requires explicit `development-partial` opt-in. A local
wheel can be installed without application dependencies; see the
[offline packaging evidence](../plans/implementation/evidence/offline-package-2026-09-26.md).

The `RuntimeCore` protocol and the top-level exported dataclasses are the
intended stable surface. Implementation-specific journal/configuration/native
helpers currently used by synthetic consumers are provisional and must not be
treated as a qualified cross-application integration contract.

## Availability consumption (C10) - the two integration paths

The catalog (`get_runtime_catalog()`),
`evaluate_runtime_availability()` and `resolve_installation()` complete
the selector contract (projection format **2**; see the installation
identity row above for the v1 -> v2 migration rules):

* **Local (Nexus Server, embedded Core):** the Server composes its
  `RuntimeCore`, runs `await runtime.discover(DiscoveryRequest())` and
  evaluates the returned inventory on ITS OWN host, then applies agent
  policy/permissions on top of the TECHNICAL states before publishing
  options to the UI. `READY_FOR_RUNTIME` is never the authorization.
* **Remote (Nexus Connector):** the Connector's Core produces the
  facts of ITS host - `evaluate_runtime_availability(inventory)` and
  `report.to_dict()` - and transmits the versioned projection to the
  Server through the Connector/Server API. The Server renders that
  executor's options from the received facts; it never re-derives
  build/platform/containment rules and never substitutes its own
  platform for the executing host's.

The UI renders received descriptors/states verbatim (state + `reasons`
per candidate); it keeps no authoritative runtime array. `OFFLINE`,
`STALE`, TTL, connection and authorization states belong to the
hosts' application layer, not to the catalog/availability projection.
`examples/availability_projection.py` runs the reference scenario -
REAL discovery of two byte-identical copies in distinct trusted roots
(the A11-01 case), attach registered-but-unqualified, missing
installation - through catalog -> discovery -> availability ->
projection -> selection -> `resolve_installation` -> existing
composition, and emits the JSON fixture (`--json`) with the acceptance
criteria for Server UI tests: every row renders state+reasons,
same-family rows never collapse (distinct refs, distinct labels),
attach never renders enabled, `NOT_PROBED` never renders ready,
`display_name`/`label` are never identities, and a projection with an
unknown `format_version` renders INCOMPATIBLE
(`AvailabilityReport.from_dict` refuses it typed). `executor_id`,
`inventory_revision` and TTL are the hosts' envelope around a
selection: a ref from another executor does not resolve against this
inventory (typed not-found); the Server validates scope/revision, the
Core never issues network endpoints.
