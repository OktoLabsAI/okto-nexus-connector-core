# nexus-connector-core

Independent, embeddable Python library for the native harness runtime shared by
Nexus Server and Nexus Connector. This repository is under active extraction.
The current `0.1.0.dev0` wheel provides immutable operation models, strict
contract negotiation, a bounded NXL r3 frame codec backed by bundled schemas,
a local SQLite operation journal, a minimal effect
admission kernel, native helpers and copied Codex/Pi/Claude/attach connector
implementations. `RuntimeCore` defines the async public contract;
`LocalRuntimeCore` implements operation admission, technical event replay,
inspection and reconciliation through an injected native factory. A private
bridge adapts the copied synchronous connectors, but the real factory fails
closed until this wheel has its own exact build/provider qualification. The
qualification key includes native kind, observed version, real platform,
binary architecture and executable SHA-256; a version string alone grants
nothing. A selected Claude executable may be probed read-only with a bounded,
secret-free `--version` call. The wheel
does not yet qualify a managed harness or a remote Connector integration.
The frame encoder checks definitely oversized or cyclic host objects before
JCS allocation; exact wire size and schema validation still run before output.

The async facade does not make shutdown/restart fully qualified: session
handles are process-local, and after restart it reports unknown ownership
while retaining durable operation receipts. `SUBMITTED` proves only that a
native call returned, not native acceptance or completion.
Where the copied adapter emits a correlated, recognized terminal outcome, the
event and terminal receipt are committed atomically; a late synchronous
`SUBMITTED` update cannot replace `SUCCEEDED`, `FAILED` or `CANCELLED`.
Operation and session lookups are scoped by `server_id` and `executor_id`;
`inspect` takes a `SessionKey`, and `reconcile` takes those namespace IDs.
Pre-namespace development journal rows are retained but quarantined: the Core
raises `LEGACY_OPERATION_UNSCOPED` for a colliding ID rather than replaying it.
The SQLite journal now enforces transactional event payload/item budgets with
separate global, Server/executor and session accounting and a critical reserve.
One noisy session cannot consume another session's normal event budget within
the same Server/executor namespace. At 80% usage it
stops admitting new work while preserving reserved slots for interrupt/close.
Durable operation rows also have a per-session cap (10,000 by default, with
100 reserved for critical controls); receipts are not automatically deleted,
so a long-lived session can eventually reach that cap.
The trusted host can record a contiguous Server durable-ingress ACK, then
compact only ACKed event bodies in bounded batches. Persistent stream metadata
prevents sequence reuse after compaction/restart; replay from a pruned cursor
reports `EVENT_GAP`. These are logical payload budgets, not yet a proven bound
on SQLite file/WAL size; automatic maintenance and disk-full fault
qualification remain open.
The journal additionally reports database/WAL/SHM bytes, applies a physical
admission guard with critical headroom, limits the main SQLite page count and
configures WAL checkpoint/retention thresholds. An explicit non-waiting WAL
checkpoint reports when a reader prevents truncation. These measures fail
closed for new work under observed pressure but do not constitute a strict
cross-process filesystem quota while WAL readers can remain active.
The wheel includes `nexus_connector_core.testing.run_journal_conformance` so
a host-supplied Journal port can be checked against the same admission,
uncertainty, event and ACK scenario as the reference SQLite implementation.
An injected monotonic clock governs the local lease. Renewal uses a
connection-generation compare-and-swap; stale generations cannot submit new
turns, revocation is irreversible for that session, and an expired owned
runtime is closed after the configured grace. Close only releases ownership
when process stop is observed. Lease/session state is still process-local, so
restart recovery and host-level reconciliation remain required.
The runtime, effect kernel and scoped native-action bridge fail closed if an
injected monotonic clock regresses or becomes non-finite; an apparent recovery
does not revive the lease or capability. This is an in-process fence, not
cross-reboot lease recovery.
`LocalRuntimeCore` bounds concurrent opens (default 8) and locally tracked
owned/uncertain sessions (default 32). A proven prelaunch refusal is a durable,
retry-safe failed receipt; an ambiguous native open retains its capacity slot
and appears as `unknown` at shutdown. These limits are per runtime instance,
not a persisted or host-wide physical process-tree quota.
Shutdown now bounds its observation time to the configured drain and interrupt
windows. An unfinished native send, close or open is reported `unknown`; its
owned capacity is not released merely because the wait expired. A late open
starts a Core-owned close, and a later shutdown can observe a pending close.
For an adapter that exposes active-turn state, shutdown waits through the
drain window and journals a technical interrupt attempt before native send.
The interrupt window then bounds observation before close. At its deadline,
a managed Core-owned backend may request independent tree containment even
when a native write remains pending; ownership is retained until that effect
settles and stop is observed. This path has local peer/process tests on
Windows and WSL2, but remains unqualified with real providers and the full
platform matrix. Attach targets are never force-stopped by the Core.

The library does not expose MCP services. MCP capable harnesses must connect
directly to the Nexus Server HTTP endpoint; native stdio remains a separate
adapter protocol.
`direct_http_config` requires an explicit approved Server origin and an
explicit loopback-reachability assertion for local harnesses. The pure
`config_document` plans explicitly selected JSON or narrow Codex TOML entries
only with host-supplied ownership evidence. The Core also has a local
cooperative lock/backup/CAS writer, but the trusted host must choose and
approve the target path and verify Windows ACLs. Neither planner stores a
secret or accepts a remote path.

The four native adapters are selected through a fixed Core-owned registry;
metadata inspection does not import their modules, and real launch remains
blocked until an exact native build is qualified. The Pi extension and its
bounded, non-HTTP local action socket are packaged in the wheel. They require
a trusted host to issue a scoped native capability and supply the canonical
domain backend; this project does not implement inbox or MCP forwarding.

The `development-partial` NXL bundle is generated entirely in this project by
`contracts/generate.py`. It covers the 20 protocol frame families and the
intent, event, error, inventory, capability and HTTP response shapes, with
positive/negative fixtures. It is not yet a normative consumer contract:
semantic cross-field checks and consumer conformance remain incomplete. A
pure `receipt_reducer` handles duplicate, out-of-order, terminal and uncertain
receipt evidence without inventing missing ACKs. The pure `event_reducer`
provides bounded batch/gap/ACK projection only after host-durable ingress.
`inventory_reducer` requires gap-free deltas and uses snapshots for
resynchronization. `lease_reducer` correlates grant to a fresh per-attempt
lease ID and computes a conservative monotonic deadline; this ID convention
and consumer integration remain pending qualification. The
canonicalizer uses the pinned, pure-Python `rfc8785` runtime dependency.
Consumers can run `python -m nexus_connector_core.conformance` with a pinned
manifest SHA-256 to verify installed schemas, fixtures and vectors offline.
The current partial development bundle requires explicit opt-in.

## Development

```text
python -m pip install -e .[test]
python -m pytest -q
python tools/build_artifacts.py
python tools/verify_wheel.py
```

See `plans/implementation/status.md` for gates and limits. Distribution and
publication require review of the inherited LICENSE and release evidence.
Public guides: [API](docs/api.md), [lifecycle and errors](docs/lifecycle.md),
[compatibility](docs/compatibility.md), [adapter provenance](docs/adapters.md)
and [security limits](docs/security.md). These guides are included in the
source distribution; the wheel keeps runtime resources without application
documentation imports.
