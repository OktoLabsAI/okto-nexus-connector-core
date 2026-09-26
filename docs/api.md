# Core API (`0.1.0.dev0`)

This is the development API of the independent `nexus-connector-core` wheel.
The trusted host supplies authority, selected binaries, workspace roots,
credentials and canonical application state. Core does not import Nexus Server
or Connector code. The supported top-level exports are listed below; native
adapter modules and `CopiedAdapterFactory` are not a public host API.

| Export | Use |
| --- | --- |
| `RuntimeCore`, `LocalRuntimeCore` | Async port and local implementation. Construct with a `SQLiteJournal`, injected native factory, selected candidates and workspace roots. |
| `ExecutionContext` | Host-issued server/executor/binding/agent/workspace identity, revisions, generations, monotonic lease deadline and allowed actions. Never derive it from a peer payload. |
| `DiscoveryRequest`, `Inventory`, `InstallationCandidate` | Discover or pass explicitly selected local native candidates; discovery is not qualification. |
| `LaunchIntent`, `PreparedLaunch`, `OpenOperation` | Prepare a selected managed launch and open a session. `open` revalidates binary/profile/root before native effect. |
| `TurnOperation`, `ControlOperation`, `CloseOperation` | Submit text, interrupt/steer a targeted turn, or close an owned session. Use a new operation ID for each new intent. |
| `NativeApprovalOperation` | Host-authorized response to one pending Codex/Claude native approval or input request. The host passes the redacted event's `native_approval` projection; the adapter checks it against its original in-memory request. |
| `Operation`, `OperationKey`, `OperationReceipt`, `intent_hash`, `submit_frame_intent_hash` | Semantic intent identity and namespace-scoped durable receipt. Reuse an operation ID only for the identical intent. |
| `SessionKey`, `RuntimeSnapshot`, `ReconcileRequest`, `ReconcileReport` | Namespace-scoped inspection and recovery queries. A missing process-local handle yields unknown ownership, not proof of stop. |
| `ClaimedSession`, `SessionClaimPage` | Paged durable session-ID history with the original open operation ID and, for new Core opens, opening connection/owner generations. These are claims, not active-process or lease observations. |
| `ProcessBirthEvidence`, `ProcessBirthRecord` | Historical OS birth identity for a Core-owned process container. PID/token are diagnostic evidence, never authority to signal or reattach after restart. |
| `ProcessBirthObservation` | One read-only, transient comparison of a stored birth to the current OS PID; it does not grant ownership. |
| `RuntimeEvent`, `EventCursor` | Durable technical event stream; cursor includes server, executor, session and stream epoch. |
| `StorageStatus` | SQLite database/WAL/SHM observation. Logical quotas are not a hard filesystem quota. |
| `OwnedSlotLedger`, `SQLiteOwnedSlotLedger` | Optional installation-wide owned-slot port and Core-owned SQLite implementation. Every runtime in that installation must receive handles to the same absolute ledger path. |
| `OwnedSlotReservation`, `OwnedSlotPage` | Bounded read-only inventory of unresolved reservations and their original open operation IDs; it is not process-liveness or release authority. |
| `ShutdownPolicy`, `ShutdownReport` | Bounded drain/interrupt observation and per-session outcome. `unknown` retains ownership. |
| `CoreError` | Typed failure with `code`, `stage`, `possible_effect`, `retry_safe` and optional `operation_id`. |
| `CONTRACT_REVISION` | Exact NXL revision required by development negotiation; see [compatibility](compatibility.md). |

`LocalRuntimeCore` implements `discover`, `prepare`, `open`, `submit`,
`control`, `decide_native_approval`, `events`, `acknowledge_events`, `compact_events`, `storage_status`,
`checkpoint_wal`, `inspect`, `claimed_sessions`, `process_birth`,
`observe_process_birth`, `reconcile`, `close`, `shutdown`, `renew_lease` and
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
`runtime.open` atomically claims its session ID in the journal namespace;
host journal adapters must implement the `claim_session` admission flag and
atomically retain the supplied opening generations with that claim. Legacy
claims without this evidence report `None`, never a guessed generation.
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
