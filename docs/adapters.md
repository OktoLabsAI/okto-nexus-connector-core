# Native adapter migration and provenance

Core owns adapted copies of `codex.py`, `pi.py`,
`claude_code_stream.py` and `claude_code_attach.py` under
`src/nexus_connector_core/native/adapters/`. It also owns the neutral helper
and process backend code they use. Runtime imports resolve within this wheel;
there is no import, editable dependency or runtime file lookup into the
sibling Nexus checkout. The exact read-only source commit, per-file SHA-256,
adaptation decisions and deliberately excluded application domain/ports are
recorded in the [extraction inventory](../plans/implementation/evidence/extraction-provenance-2026-09-25.md).

The static Core registry maps only `codex_app_server`, `pi_rpc`,
`claude_stream` and `claude_attach` to classes and allowed platforms. Peer
data may select an ID, never a module path or factory. Metadata inspection
does not import the adapter module; the selected class loads lazily after
registry/platform checks. Exact native qualification is still empty, so
shipping copied code is not a claim of provider support.

The Codex runtime bridge settles a submitted operation only after a
`turn/started` identity and a matching `turn/completed` identity are observed.
An old, missing or malformed native turn ID faults the event stream rather
than crediting the terminal to the newer operation. Recently completed turn
IDs (256 per Core session) are retained to reject an immediately replayed
`turn/started`; this bounded replay fence is not a provider-version
qualification or a substitute for real-turn ordering tests.

The Pi bridge requires an observed `agent_start` for the active submit before
an ID-less `agent_settled` can reduce that operation's receipt. A stale
terminal arriving between a new prompt ACK and its start faults the event
stream while leaving the submitted operation unsettled. Pi does not attach a
turn ID to these events, so this is a conservative ordering fence, not full
correlation against arbitrary delayed start/terminal pairs. The observed
single Pi 0.87.1 provider turn does not qualify controls or failure paths.

The user-supplied Windows Pi 0.87.1 installation was observed through an
explicit Node executable and release CLI JavaScript. Its no-turn RPC
`get_state` response echoed the sent ID. The copied Pi adapter therefore
uses ID-and-verb correlation for that exact version, with a bounded 32-request
window, while earlier ID-less observations retain serialized verb matching.
The provided `bin/pi` is a shell launcher, not a trusted Windows binary
selection. A trusted local host can explicitly select the Node executable
and installed package CLI through `candidate_pi_node_cli`; Core binds both
files to one composite fingerprint, probes the CLI version, and verifies
both again before launch. This is launch preparation, not a production
qualification; real provider control/error campaigns remain open. One
explicitly authorized Windows
0.87.1 model turn with no tools or automatic retry reached `agent_start` and
`agent_settled` with assistant stop reason `stop`; this is not a blanket
capability grant. See the [0.87.1 observation](../plans/implementation/evidence/pi-0.87.1-rpc-observation-2026-09-26.md).

The Pi connector's default version probe now targets `node cli.js --version`
for this compound launch, not `node --version`. A rejected `prompt`, `steer`
or `abort` response is surfaced as an error and fails the send; because bytes
crossed the native pipe, the Core journal conservatively records an unknown
possible effect, never a submitted/successful command. This does not claim
the rejection is a pre-write refusal.

Public Pi steer now uses an ID-less target contract. `turn.steer` is
admitted only without `expected_turn_id`; naming a native turn ID is
refused before operation admission because Pi's wire has no turn
vocabulary. The target is the agent run Core observed starting
(`agent_start`) for the active submit: with no active submit or no observed
start, the bridge refuses before the native write with a retry-safe
`STALE_TURN`. Delivery follows Pi's native next-turn-boundary steering
queue (`queue_update`), and the steered content remains part of the same
active turn; a follow-up after `agent_settled` is a new `turn.submit`.
This contract is verified against contained peers, the copied-adapter
bridge, the public runtime/journal, and — under explicit user
authorization — against real Pi 0.87.1 on Windows: the steer queued
(`queue_update` with a non-empty steering list), drained at the next turn
boundary as a user message, and the turn settled only at `agent_settled`.
Sustained-load, retry and Linux provider behavior remain unqualified.

Claude stream has no steer vocabulary: public `turn.steer` is refused for
`claude_stream`, and adapter-level steer/interrupt during the fatal
requesting window are refused before the native write (a durable safe
failure). The honest control semantics are therefore queue-free:
interrupt while generating lands a native `control_request` interrupt and
the turn ends with its real result subtype (`error_during_execution` when
interrupted, verified against real Claude 2.1.282), and any follow-up is a
new `send_turn` reprompt on the same stream-json process — interrupt-then-
reprompt, never steering. Requesting-phase refusal itself remains covered
by synthetic pre-write tests.

Native approval/input handling is disabled by default in the copied Codex
and Claude stream adapters. An explicitly opted-in factory can expose their
bounded native requests as technical events; the trusted host must authorize
and journal each `NativeApprovalOperation` through Core before the adapter
replies. The original in-memory request, not caller-edited method/tool data,
determines the native response shape. No automatic approval is supplied.

Application state stays in Server/Connector. Core does not copy the Nexus
supervisor, domain model, canonical inbox, HTTP routes or MCP server.
Native-action requests use a scoped injected backend, not application imports.
MCP-capable harness configuration points directly to the Server HTTP endpoint;
native stdio/JSONL remains a separate adapter protocol.
