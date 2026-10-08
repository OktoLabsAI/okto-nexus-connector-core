# Operations, leases and uncertain outcomes

The host issues a scoped `ExecutionContext`. `prepare` validates identity and
the selected candidate without starting a provider. It requires a finite,
numeric monotonic lease deadline; `open` also rejects a lease/grace window
that overflows finite time arithmetic before admission. `open` rechecks the
prepared binary/profile/root, reserves capacity, journals the operation and
starts the native session/event pump. `submit` and `control` journal intent
before an effect-capable native send. `close` retains ownership until stop is
observed. `shutdown` first drains, then attempts a technical interrupt for a
known active turn, then requests owned-tree containment when available. Attach
targets are external and are never force-stopped by Core.
Malformed or overflowing shutdown drain/interrupt budgets are rejected before
the runtime enters drain.
Managed opens reserve a durable owned slot in the technical journal before
native launch. The default shared-journal cap is eight, and all journal
connections using that file must agree on it. An uncertain launch retains its
slot across restart; proven prelaunch refusal or observed stop releases it.
Both ledger variants expose a paged read-only inventory of unresolved slot
reservations. That inventory can guide trusted-host reconciliation after a
restart, but neither its presence nor absence proves native process liveness;
it never triggers automatic release.
This bounds instances sharing **one SQLite journal**, not separate journals
or a whole installation unless the trusted host supplies a common ledger.
Core provides `SQLiteOwnedSlotLedger` for that purpose: all runtime instances
must open the same installation-owned absolute local file and inject it as
`owned_slot_ledger`. A different file, copied database or missing injection
cannot be treated as the same physical capacity domain. The ledger is not a
process-containment handle or proof that a reservation's process is alive.

An `OperationReceipt.stage` of `SUBMITTED` means the Core native call returned;
it does **not** prove provider acceptance, execution or completion. A
correlated terminal event may atomically produce `SUCCEEDED`, `FAILED` or
`CANCELLED`. `OUTCOME_UNKNOWN` means an effect might have happened without
enough evidence. Do not replay a possible effect under a new operation ID.
Query `reconcile` with the original `OperationKey` and session namespace,
consume durable events, and seek external/provider evidence when needed.
`retry_safe=True` is meaningful only with `possible_effect=False`; a proven
pre-write refusal can be retried according to host policy. A duplicate
operation ID with a different semantic intent raises `OPERATION_CONFLICT`.
The journal also claims a `runtime.open` session ID once per Server/executor
in the same transaction as operation admission. Repeating the exact open
operation returns its old receipt; a new operation ID cannot reuse that
session ID after close, failure or restart. Even a proven pre-write failure
requires a fresh session ID for a new open attempt. This is a durable
identity fence, not proof that an old native process was stopped.
`project_r4_resource_release` also accepts an effect-capable failed opening
when the exact opening claim and independently released owned slot match.
This proves resource release without rewriting its `FAILED` receipt. A host
may recover a separately proven never-dispatched first message under current
authority; the failed opening itself is not replayed.
After restart, a trusted host can scan `claimed_sessions` for one
Server/executor namespace. The first page fixes a journal rowid high-water
mark; subsequent pages reuse it, so claims inserted later are outside that
scan and require a fresh sweep. Pages are bounded to 4,096 entries (default
128). New Core opens also retain their opening `connection_generation` and
`session_owner_generation` in the same transaction as the claim and receipt.
These are immutable opening evidence, not current generations; older claims
report `None`. Every returned ID is historical, not a live owner or valid lease;
`inspect` remains `unknown` without a process-local binding.
For Core-owned launches, `process_birth` may return a durable historical
container PID and OS birth token (Windows process creation FILETIME or Linux
guardian boot ID/start tick) tied immutably to the original open claim. Attach
targets have no Core-owned birth record. A missing record is possible if the
owner crashed between spawn and journal commit; a present record never grants
authority to kill or reattach by PID. After restart, physical ownership and
lease state remain unknown even when this record exists.
`observe_process_birth` may compare the stored token to a current read-only
OS observation. A matching live PID can exit immediately afterward; a
different birth demonstrates PID reuse, while missing/inaccessible evidence
stays conservative. No observation changes `inspect` ownership, renews a
lease, frees an owned slot, or authorizes kill/reattach.

The local lease is measured with an injected monotonic clock. A decreasing or
non-finite observation fences new work; apparent clock recovery does not
revive the lease. `renew_lease` compares connection generation and ownership
generation, and `revoke_lease` is irreversible for that session. Successful
renewal or revocation waits for previously admitted normal and control native
sends on that session to finish before changing the context. The wait is
bounded by `reconnect_fence_seconds` (default 5 seconds); `RECONNECT_BUSY` or
`REVOKE_BUSY` means no lease update was applied and the host must retry or
reconcile, not assume the old channel is fenced. This in-process fence does
not establish durable takeover after a Core restart. Expiry stops
new normal submissions and schedules owned close after grace. Lease and
process-handle ownership are process-local; after a runtime restart, durable
receipts survive but physical ownership is unknown until the trusted host
reconciles it. An await timeout or shutdown deadline does not prove a native
thread or child process stopped, and the owned slot remains reserved.

Events are durable in the Core journal before the optional sink is called.
The sink is a best-effort notification path, delivered by one independent
task per session from journal replay: a slow callback does not block native
pipe consumption or create an unbounded in-memory queue. A failed callback is
retried when another event is appended, including one that arrived while the
callback was still running; hosts must use `EventCursor` replay
for recovery rather than assume every notification arrives. A pruned cursor
raises `EVENT_GAP`. The host records
a contiguous durable-ingress ACK before `compact_events` can remove ACKed
event bodies. Each explicit compaction batch is bounded to 1-4,096 rows
(default 128), including when the host injects its own journal port. The
journal reserves critical capacity and enforces global,
Server/executor and session event byte/item budgets. Saturation of one session
blocks its new normal work but not another session's budget; urgent critical
work remains subject to finite global and local reserves. Durable operation
rows likewise have global, Server/executor and per-session caps with critical
reserves; receipts are not
automatically compacted, so a long-lived session may reach its operation cap.
A pinned SQLite reader can still grow the WAL; the package does not claim a
hard filesystem bound.
Before a new normal operation or event crosses the physical headroom gate,
or a normal event would exceed its logical byte/row quota, the journal makes
one bounded attempt to compact already-ACKed event bodies and truncate the
WAL. Event maintenance prioritizes the pressured session, then its
Server/executor. Critical events bypass this maintenance delay. A busy reader
or insufficient eligible data can still result in `JOURNAL_FULL`.

`CoreError` fields are machine-readable. Common codes include
`BINDING_NOT_AUTHORIZED`, `AGENT_REVOKED`, `STALE_GENERATION`, `PROFILE_DRIFT`,
`RECONNECT_BUSY`, `REVOKE_BUSY`, `CAPACITY_EXCEEDED`, `SESSION_CONFLICT`,
`SESSION_UNKNOWN`, `SESSION_CLOSED`,
`STALE_TURN`, `NATIVE_REQUEST_NOT_OBSERVED`, `CAPABILITY_UNSUPPORTED`,
`OPERATION_CONFLICT`, `JOURNAL_FULL`,
`EVENT_GAP` and `OUTCOME_UNKNOWN`. This list is illustrative; do not infer
retryability from the code string alone. Use `possible_effect`, `retry_safe`
and the durable receipt.
