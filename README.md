# okto-nexus-connector-core

Independent, embeddable Python library that owns the **native agent-harness
runtime** shared by the Okto Nexus products: discovering, preparing,
launching, controlling, observing and shutting down managed harness
processes, plus the technical journal and contracts behind those
operations. The same wheel is consumed embedded by Nexus Server (local
runtimes) and by the Nexus Connector daemon (remote runtimes); the Core
imports neither application.

- Distribution `okto-nexus-connector-core`, import `nexus_connector_core`,
  Python ≥ 3.11, src-layout, `py.typed`, pure-Python runtime dependencies
  (`rfc8785`, `jsonschema`).
- Current version: `0.0.2`.
- First release version: `0.0.1`. Importing the
  package opens no socket, spawns no thread/process, starts no event loop
  and reads no credentials.

## What the Core is

### Automatic runtime operation

`DEFAULT_RUNTIME_AUTOMATION` enables automatic message delivery and recovery.
Portable connection configurations normalize the compatibility field
`automatic_reply` to `true`, including configurations used by Connector CLI.
Delivery still requires an enabled runtime, a recipient and current authority.
Portable configurations accept only `local` or `remote` for `execution_location`;
the removed `all` value is rejected instead of implying a fallback order.

Hosts use `RuntimeAutomation` for the shared supervision behavior:

- `recover(...)` retries an initial failed reconciliation, with delays of
  2, 4, 8, 16 and 30 seconds. An optional host setting can suspend recovery;
  turning it back on resets the retry budget. Pending work for independent
  executors may progress while the current owner remains blocked.
- `supervise_connection(...)` owns automatic Connector reconnects and bounds
  recovery failures separately from transport reconnects. Exhaustion is exposed
  as `RECOVERY_ATTENTION_REQUIRED`; restarting the daemon starts a new budget.
- Both methods join in-flight callbacks on cooperative stop. They never retry
  a submitted native operation, invent an ownership proof or bypass approval.

The host callbacks verify Core journal/resource/event proofs and commit current
authority before declaring readiness. Nexus owns inboxes, routing, transactional
claims and durable pending messages; Connector owns its authenticated connection
and dispatch lanes. Core owns the common defaults, retry scheduling and budgets.
This split keeps the same behavior on a Nexus host and on the CLI machine without
making Core depend on either application's database or transport.

| Area | Delivered by |
| --- | --- |
| Discovery & selection | Trusted-path/explicit candidate selection, bounded PE/ELF/Mach-O architecture parsing, sealed read-only version probes (`--version`-class, secret-free) |
| Profiles & launch | Typed argv realization (spaces/Unicode safe, no shell), workspace/root validation, drift revalidation between prepare and open, composite Pi Node+CLI fingerprinting |
| Managed adapters | Codex app-server (JSON-RPC), Pi RPC (JSONL over stdio), Claude Code stream-json, Claude attach (external, POSIX substrate) |
| Process ownership | Windows Job Objects and Linux guardian/pidfd backends, birth records and read-only observation, kill-on-close containment, per-tree process limits and census |
| Journal & kernel | SQLite technical journal (admissions, effect markers, receipts, events, ACK/compaction, quotas, hard WAL bound), minimal effect-admission kernel with honest uncertainty |
| Session governance | Durable session-ID claims with opening generations, durable lease fence (journal CAS), lease renewal/revocation, inspect/reconcile |
| Events | Bounded ingest/replay/ACK, per-session fairness and byte/item caps, slow-subscriber isolation, explicit gaps, redaction boundary |
| Contracts | Core-owned NXL r3 bundle: 20 frame families, intents/events/errors/inventory/capabilities/HTTP shapes, fixtures and JCS hash vectors, offline verifier |
| Harness integration | Declarative direct-HTTP MCP client configuration (data only), typed non-MCP native-action bridge, packaged Pi extension |

## What the Core is not

- **No MCP implementation.** No MCP server, proxy, relay, stdio facade or
  SDK helper exists here. MCP-capable harnesses connect directly to the
  Nexus Server HTTP endpoint; the Core only *configures* those native
  clients. Stdio of the native adapter protocols is not MCP.
- **No Nexus application.** No canonical identity, inbox, handoffs,
  grants, HTTP/WSS routes, dashboard or user store. The trusted host
  supplies authority (`ExecutionContext`) and canonical backends.
- **No daemon.** The host owns startup/shutdown and the event loop.

## Layout

```text
src/nexus_connector_core/
  contracts/nxl/v1/     # generated schema bundle, manifest, fixtures, vectors
  native/adapters/      # codex.py, pi.py, claude_code_stream.py, claude_code_attach.py
  native/process/       # owned process backends, birth records, census
  journal.py kernel.py  # SQLite technical journal + effect-admission kernel
  runtime.py            # LocalRuntimeCore: the async public facade
  discovery.py profiles.py environment.py harness_config.py
  native_action_bridge.py native_action_socket.py pi_extension_resource.py
  testing/              # Journal / owned-slot conformance kits
contracts/              # generator sources for the bundled NXL artifacts
docs/                   # api, adapters, compatibility, lifecycle, security
plans/implementation/   # status, acceptance matrix, evidence log
tools/                  # build/verify/probe and campaign scripts
```

## Managed adapters and production qualification

To implement another harness, follow
[Adding a native harness runtime](docs/adding-a-runtime.md). It covers the
registry, discovery, native transport, configuration/JSON import, Nexus tools,
human input, qualification tests, and rollout to Server and Connector.

Qualification is **exact**: native kind, observed version, real platform,
parsed architecture and the selected file fingerprint (for Pi, a composite
binding the trusted Node executable *and* the installed CLI JavaScript).
Any drift — version, OS, architecture, file bytes — loses the grant; a
version string or synthetic peer grants nothing. The allowlist lives in
`native/adapters/compatibility.py`.

| Adapter | Qualified builds (production) | Controls | HITL |
| --- | --- | --- | --- |
| `codex_app_server` | 0.157.0, win32/x86_64, exact `codex.exe` fingerprint | steer + interrupt with expected native turn ID; concurrent threads verified | `item/commandExecution/requestApproval` (decline + tardy refusal verified) |
| `pi_rpc` | 0.87.1, win32/x86_64, composite Node+CLI fingerprint | ID-less queued steer (next-turn-boundary) + abort; settle-before-ack wire order verified | extension UI auto-cancel contract (see docs/adapters.md) |
| `claude_stream` | 2.1.282, win32/x86_64, exact `claude.exe` fingerprint | interrupt while generating (no steer vocabulary — refused honestly) | `can_use_tool/Write` (forged-kind refusal + decline verified) |
| `claude_attach` | — (unqualified; POSIX substrate) | attach lifecycle gated | — |

All qualification evidence (real campaigns, contained peers, fault cuts)
is recorded under `plans/implementation/evidence/`; the acceptance matrix
in `plans/implementation/matrix.md` states exactly what ran and what
remains blocked.

## Quickstart (embedded host shape)

```python
from nexus_connector_core import (
    CloseOperation, ExecutionContext, LaunchIntent, LocalRuntimeCore,
    OpenOperation, ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory

journal = SQLiteJournal("executor-journal.db")

async def environment(prepared):     # trusted host resolves the overlay
    return {"CODEX_HOME": "..."}     # essentials + provider auth refs

runtime = LocalRuntimeCore(
    journal, CopiedAdapterFactory(environment),
    candidates={"codex_app_server": selected_candidate},
    workspace_roots={"ws": "/abs/root"})

context = ExecutionContext(
    "server", "executor", "binding", "agent", "ws",
    authorization_revision=1, configuration_revision=1,
    connection_generation=1,
    lease_deadline_monotonic=now + 90,          # host monotonic clock
    allowed_actions=frozenset({"runtime.open", "turn.submit",
                                "turn.interrupt", "runtime.close"}))

prepared = await runtime.prepare(
    LaunchIntent("agent", "ws", "codex_app_server"), context)
await runtime.open(OpenOperation("open-1", "session", "epoch", prepared), context)
await runtime.submit(TurnOperation("turn-1", "session", "hello"), context)
async for event in runtime.events(EventCursor(
        "server", "executor", "session", "epoch")):
    if event.payload.get("delivery_phase") == "terminal":
        break
await runtime.close(CloseOperation("close-1", "session"), context)
report = await runtime.shutdown(ShutdownPolicy(5, 5))
```

A runnable end-to-end reference (real selection → probe → prepare →
allowlisted factory → real turn → correlated receipt → bounded shutdown)
is `tools/probe_managed_factory.py`.

## Operational guarantees, and their honest limits

- **Receipts never lie.** Every mutable intent gets a durable
  `operation_id` and semantic `intent_hash` before any effect; duplicates
  return the known receipt, conflicting hashes raise `OPERATION_CONFLICT`.
  `SUBMITTED` proves only that the native call returned — terminals
  (`SUCCEEDED`/`FAILED`/`CANCELLED`) come from correlated native evidence
  and commit atomically with the event. A rejected or ambiguous outcome
  stays `OUTCOME_UNKNOWN` with `possible_effect` rather than being retried
  automatically.
- **Bounded journal.** Transactional event/operation budgets with global,
  Server/executor and session accounting plus a critical reserve for
  interrupt/close; ACKed-only compaction; page-count cap; and a **hard WAL
  admission ceiling** (`max_wal_bytes`/`reserved_wal_bytes`) with automatic
  bounded-truncate maintenance — a pinned reader stops admissions with a
  typed `JOURNAL_FULL` instead of unbounded WAL growth. These are logical
  quotas, not an OS filesystem quota. Host journal adapters must pass the
  bundled conformance kits (`nexus_connector_core.testing`).
- **Durable session governance.** `runtime.open` atomically claims the
  session ID (with opening generations) in the journal namespace;
  `renew_lease`/`revoke_lease` advance a durable lease fence via journal
  CAS before any in-memory change — a stale or competing renewal fails
  `STALE_GENERATION`, durable revocation is irreversible, and
  `persisted_lease()` exposes the last fence as reconciliation evidence
  (never liveness or takeover authority).
- **Owned processes only.** Managed children run inside Windows Job
  Objects (kill-on-close) or the Linux guardian; birth records allow
  read-only post-restart identity comparison. Launches may set
  `max_tree_processes` — kernel-enforced via the job object on Windows,
  reported as unenforced on Linux — and `owned_tree_census` provides a
  bounded PID census. Force-stop reaches only Core-owned trees; attach
  targets are external and never killed by the Core.
- **Bounded lifecycle.** Concurrent opens and owned sessions are capped
  per installation (owned-slot ledger, default 8); shutdown observation is
  finite with honest per-session outcomes (`graceful`/`forced`/`unknown`);
  a regressing or non-finite monotonic clock fails closed. After a host
  restart, ownership is reported unknown while receipts, claims, births and
  lease fences survive — hosts reconcile rather than guess.

## Tools/MCP boundary and the native-action bridge

`harness_config` generates **declarative direct-HTTP MCP client
configuration** for harnesses (URL + environment-bound `mcp-cap:` secret
refs, never literal tokens) and composes with third-party entries under
host-supplied ownership proof. Harnesses without an MCP HTTP client get an
explicit unsupported-transport diagnostic — there is no stdio fallback.
For harnesses without MCP, the typed **non-MCP native-action bridge**
(context/handoff actions against an injected canonical backend) and the
packaged **Pi extension** (offline, pinned build, three explicit tools,
loopback JSONL ingress) provide structured integration; free model text is
never parsed as a Nexus action.

## Contract bundle and conformance

`contracts/generate.py` produces the NXL r3 bundle shipped in the wheel:
schemas for all 20 frame families plus intent/event/error/inventory/
capability/HTTP shapes, positive/negative fixtures, JCS hash vectors and a
hashed manifest. The bundle is currently `development-partial` (explicit
opt-in) until consumers pin it as normative. Verify an installation
offline:

```bash
python -m nexus_connector_core.conformance --manifest-sha256 <sha>
```

## Development

```bash
python -m pip install -e .[test]
python -m pytest -q
python tools/build_artifacts.py            # normalized wheel + sdist
python tools/verify_wheel.py               # clean-wheel import/resources
python tools/verify_offline_artifacts.py --wheelhouse <dir>
python tools/validate_release.py --version 0.1.0.dev0 --allow-development
```

The local verification matrix is Windows and WSL2 (Ubuntu) × Python
3.11–3.13, including offline installs of both artifacts. Hosted CI and the
protected release workflow are staged in `.github/workflows/` but remain
unexecuted (GitHub Actions billing); publication requires the joint
review described in `docs/security.md`.

Guides: [API](docs/api.md) · [adapters & provenance](docs/adapters.md) ·
[compatibility matrix](docs/compatibility.md) ·
[lifecycle & errors](docs/lifecycle.md) · [security limits](docs/security.md).
Implementation gates, the acceptance matrix and the evidence log live in
[plans/implementation/](plans/implementation/status.md).

## License

Elastic License 2.0 with the Okto Labs SaaS/Branding Addendum —
Copyright 2026 Okto Labs. The full [LICENSE](LICENSE) is identical to
the Okto Nexus license and is authoritative. Commercial clarification:
dev@oktolabs.ai. See [CONTRIBUTING.md](CONTRIBUTING.md) for branch and review rules.

## Global harness MCPs

See [MCP inheritance](docs/mcp-inheritance.md) for host-local MCP configuration,
agent/global policy inheritance and version requirements.
