# Adding a native harness runtime

This guide describes the extension points in Core `0.2.61.dev0`. Use it to
add a new managed harness implementation that Nexus Server can run locally
and Nexus Connector can run remotely. All paths below are relative to this
repository. Read the code at the version you are changing: the native bridge
is an internal implementation, not a stable third-party plugin API.

**A new runtime requires code, tests, and a new Core distribution.** The
registry is static. A JSON settings file selects parameters for an existing
adapter; it cannot register a module, executable factory, or new protocol.

Plan the full scope before starting. Following this guide produces, in
order:

1. a recorded integration contract (§1), including the platform containment
   check;
2. registry and catalog entries plus the audited per-adapter branches (§2);
3. passive discovery, the bounded version probe and launch preparation (§3);
4. the native adapter and its bridge wiring (§4);
5. settings validation and the portable JSON format (§5);
6. Nexus tool and native question integration (§6);
7. synthetic-peer tests plus real-harness campaign evidence (§7);
8. a new Core distribution with regenerated contracts, updated consumer pins,
   updated documentation and end-to-end consumer validation (§8).

Expect to touch roughly fifteen source files, add coverage in the seven test
areas of §7, and release a new Core version consumed by both Nexus Server and
Nexus Connector.

## 1. Define the integration contract

Choose a stable `adapter_id`, such as the illustrative `acme_rpc`, and a
`native_kind`, such as `acme`. The ID describes an integration mode, not an
agent, account, model, or installation. Multiple agents and installations
can use the same adapter ID.

Record the native protocol before implementing it:

| Question | Required decision |
| --- | --- |
| Launch | Exact argv, working directory, environment, handshake, readiness signal, and supported OS/architecture |
| Identity | Native session/thread IDs, turn IDs, request IDs, and whether concurrent sessions share a process |
| Output | Delta versus cumulative snapshot semantics; how successful, failed, and interrupted turns terminate |
| Controls | Whether steer and interrupt exist, their target IDs, and immediate versus next-turn-boundary delivery |
| Questions | Native tool approval and user-input methods, answer types, cancellation, and expiry behavior |
| Configuration | Model, provider, effort, permission mode, sandbox, defaults, and read-only discovery methods |
| Shutdown | Graceful close, process-tree containment, observed termination, and recovery after a lost response |
| Nexus tools | Native HTTP MCP configuration or an explicit typed native-action extension |

Existing ID suffixes record the transport/lifetime mode: `_rpc` for
request/response RPC over stdio, `_stream` for stream-json protocols,
`_app_server` for long-lived app-server processes, and `_attach` for
attaching to a process Core does not own. Pick the closest mode. The
`adapter_id` → `native_kind` pair is declared once in `AdapterSpec` and
constrains the `harness_kind` values accepted by
[`adapter_types.py`](../src/nexus_connector_core/native/adapter_types.py).

Unsupported controls must return an unsupported/refused result. Do not
simulate steering by silently creating a new turn, infer success from a
write to stdin, or interpret assistant prose as a Nexus tool invocation.

The ownership boundary is:

```text
Nexus Server / Connector host
  canonical agent, recipient, workspace, policy, grants, UI and transport
        |
        v
LocalRuntimeCore + journal + leases + owned process lifecycle
        |
        v
native adapter: protocol requests, correlated events, native responses
        |
        v
harness process
```

Core must not import either consumer application. An adapter does not own
the inbox, handoff state, or recipient routing. The host binds incoming
work to the appropriate Core session and routes the resulting events.

### Platform containment prerequisite

Managed execution requires a qualified owned-process containment backend
for the target OS: Windows job objects, the Linux pidfd guardian or the
Darwin launchd-coalition backend, all under `native/process/` (see
[`preflight.py`](../src/nexus_connector_core/native/process/preflight.py)).
Passive
discovery and every native open call `require_containment()` first; on an
unqualified host or login session the attempt fails with the typed
`PROCESS_CONTAINMENT_UNAVAILABLE` error instead of falling back to a bare
`kill(pid)`. Declaring a new platform in an `AdapterSpec` therefore means
either an already-qualified backend exists there, or adding and natively
qualifying one is part of the work — the
[macOS campaign](../plans/implementation/evidence/macos-native-acceptance-20261002.md)
records what that qualification looked like. The passive check is
`containment_preflight()`; it never launches a process, and an active
bootstrap probe is never part of discovery.

## 2. Register metadata and update closed adapter branches

Add an `AdapterSpec` to
[`native/registry.py`](../src/nexus_connector_core/native/registry.py).
Declare the module/class, managed mode, executable name, implementation
platforms, and truthful `ControlTargeting` metadata. Only trusted source
code supplies module and class names; remote data may select an ID only.
Metadata enumeration must not import the adapter or start a process.

In [`catalog.py`](../src/nexus_connector_core/catalog.py), add a readable
display name, harness family, and support status. Keep an incomplete adapter
`registered_unqualified`. Catalog presence and `managed_supported` do not
grant installation readiness or execution authority.

Adding a registry entry alone is insufficient. Audit these explicit branches:

| Source | What to implement or review |
| --- | --- |
| [`native/adapter_types.py`](../src/nexus_connector_core/native/adapter_types.py) | Allowed `harness_kind` values in `HarnessSession` and `HarnessEvent` |
| [`discovery.py`](../src/nexus_connector_core/discovery.py), [`discovery_layouts.py`](../src/nexus_connector_core/discovery_layouts.py) | Installation layouts, version probe dispatch, fingerprint checks |
| [`profiles.py`](../src/nexus_connector_core/profiles.py) | Supported managed IDs, validated settings, deterministic argv and profile identity |
| [`native/runtime_bridge.py`](../src/nexus_connector_core/native/runtime_bridge.py) | Constructor dispatch, launch guards, event/turn correlation, input handling, close observation |
| [`runtime.py`](../src/nexus_connector_core/runtime.py) | Adapter-specific capability, control, and native-request paths |
| [`native/adapters/compatibility.py`](../src/nexus_connector_core/native/adapters/compatibility.py) | Protocol observations and separately qualified capabilities |
| [`harness_configuration.py`](../src/nexus_connector_core/harness_configuration.py), [`models.py`](../src/nexus_connector_core/models.py) | Settings vocabulary, validation, passive description, native observation |
| [`environment.py`](../src/nexus_connector_core/environment.py), [`provider_discovery.py`](../src/nexus_connector_core/provider_discovery.py) | Approved environment mapping and optional login-directory hint |
| [`harness_config.py`](../src/nexus_connector_core/harness_config.py), [`config_document.py`](../src/nexus_connector_core/config_document.py) | Native HTTP MCP template and configuration representation, if supported |

For an audit starting point, run:

```sh
rg -n 'codex_app_server|pi_rpc|claude_stream|claude_code' src contracts tests
```

(`grep -rn` with the same pattern works if ripgrep is unavailable.)
Review each match for semantics; do not perform a bulk rename or assume the
existing Claude constructor fallback works for another harness.

## 3. Discover and prepare the selected installation

Passive discovery identifies files without running them or reading login
secrets. Preserve the distinction between installation reference, selected
file fingerprint, portable build identity, and version observation. See
[`installation.py`](../src/nexus_connector_core/installation.py),
[`build_identity.py`](../src/nexus_connector_core/build_identity.py), and
[executor inventory](executor-inventory-r4.md).

Implement an explicit, bounded version probe for the new ID. Follow
`_probe_selected_version`: use the owned process backend, filter the
environment, and verify the selected identity before and after execution.
An interpreter-based harness must identify the interpreter, entry point,
and relevant dependency closure; checking only `node --version` or
`python --version` does not identify the harness.

`prepare_launch` must construct an argv tuple without a command shell,
validate the workspace and settings, and include settings in the prepared
profile fingerprint. Revalidate at launch after asynchronous callbacks
and immediately before native effects.

The workspace identity is the resolved directory and its filesystem
identity, not its contents, size, or modification time. Creating files in
an authorized workspace must not cause `PROFILE_DRIFT`; replacing the root
or redirecting a symlink/junction must. Preserve the coverage in
[`test_workspace_launch_identity.py`](../tests/test_workspace_launch_identity.py).

`discover_provider_home` may return an existing directory as a host-local
UI hint. Respect the harness's environment override, do not read credential
contents, and do not treat the hint as consent to use an account. Credentials
come from host-approved references through the existing environment boundary.

## 4. Implement the native transport and bridge

Create the adapter under `src/nexus_connector_core/native/adapters/`.
Choose the closest protocol reference:

- [`codex.py`](../src/nexus_connector_core/native/adapters/codex.py): JSON-RPC,
  correlated requests, threads, and native turn IDs.
- [`pi.py`](../src/nexus_connector_core/native/adapters/pi.py): JSONL RPC,
  ID-less turn-event ordering, queued steering, and extension UI requests.
- [`claude_code_stream.py`](../src/nexus_connector_core/native/adapters/claude_code_stream.py):
  stream-json input/output and control requests.

The object lifecycle around an adapter is:

```text
NativeFactory.open            async host contract (ports.py)
  -> CopiedAdapterFactory.open constructs the adapter, guards the launch,
     starts it on a worker and wraps the result
  -> CopiedAdapterSession      owns send/events/close/force_stop/observe,
     running them on reserved executor pools
  -> _CopiedConnector          your adapter: protocol work only
```

Your adapter implements only the bottom layer; sessions, executor pools,
secret redaction, launch guards and the runtime binding come from the
bridge.

The current synchronous connector interface is `_CopiedConnector` in
`native/runtime_bridge.py`:

```python
def start(self, *, owning_agent_id: str) -> HarnessSession: ...
def send(self, session: HarnessSession, command: HarnessCommand) -> None: ...
def events(self) -> Iterator[HarnessEvent]: ...
def close(self) -> None: ...
def force_stop(self) -> None: ...
def observe_lifecycle(self, session: HarnessSession) -> Mapping[str, Any]: ...
```

These signatures describe the interface, not a runnable adapter skeleton.
Implement the lifecycle metadata, owned-process evidence, effect guards,
and constructor arguments consumed by `CopiedAdapterFactory` and
`CopiedAdapterSession`. Merely implementing the six methods is insufficient.
The async host contracts remain in [`ports.py`](../src/nexus_connector_core/ports.py).

Use the existing bounded framing, event buffers, redactor, and owned process
facilities. Drain stdout and stderr concurrently. Keep blocking protocol
work off the host event loop, and preserve reserved capacity for containment.
Every spawn/write must check the live authorization/lease fence at the actual
effect boundary, including after waiting for locks or worker capacity.

Emit `HarnessEvent` values with the correct native session/turn identity and
delivery phase. Set `output_snapshot` accurately so cumulative text does not
lose its prefix or get appended twice. The bridge must associate terminal
events with the operation that actually started; late, duplicate, or unrelated
events cannot complete another turn. Use
[`event_ingest.py`](../src/nexus_connector_core/native/event_ingest.py) for the
existing public event translation and durable identity boundary.

Distinguish a proven pre-write refusal (`RuntimeCommandNotSent` /
`EffectNotSent`) from a rejection or timeout after bytes may have been sent.
Preserve `OUTCOME_UNKNOWN` where the native result is uncertain. Do not add
automatic replay of potentially productive operations. Close is successful
only with the required native/process termination evidence, not merely because
the close command was accepted. See [lifecycle](lifecycle.md).

## 5. Expose harness-specific settings and JSON import

Extend `validate_harness_settings` and `discover_harness_configuration` for
the new ID. Reuse `HarnessSettings` fields only when their meaning matches;
new fields require changes to the typed model, validation, profile hashing,
native launch mapping, and relevant wire/configuration schemas.

For each parameter, expose its native name, type, choices, scope, default
provenance, availability, and whether Core actually applies it (`core_applies`).
Map model selection through `LaunchIntent.model` and the harness's real
launch/thread mechanism. An omitted value should preserve the documented
native/Core default rather than silently saving a discovered default.

Implement read-only native configuration queries only when the protocol
supports them. Bind observations to the selected installation and account;
bound time, response size, and pagination. Model-specific effort values
belong to that model. Never manufacture a successful empty catalogue after
a discovery failure. See [harness configuration](harness-configuration.md)
for the passive description, authenticated observation, lifecycle event,
and consumer responsibilities.

The existing portable file format is:

```json
{
  "format": "nexus-harness-config",
  "version": 1,
  "adapter_id": "pi_rpc",
  "settings": {
    "model": "glm-5.3",
    "provider": "zai",
    "effort": "low"
  }
}
```

This is a settings example for an existing adapter, not proof that an account
can use that model. A new adapter uses its own ID and validated settings once
implemented. Use `parse_harness_configuration_file` and
`export_harness_configuration_file` from
[`configuration_file.py`](../src/nexus_connector_core/configuration_file.py).
Files contain no credentials, executables, observations, or authorization.
The current parser rejects unknown top-level keys, duplicate keys, mismatched
adapter IDs, unsupported settings, and files larger than 65,536 UTF-8 bytes.

## 6. Connect Nexus tools and native questions

Keep these three mechanisms separate:

| Mechanism | Integration responsibility |
| --- | --- |
| Harness tool approval | Apply a supported native permission/approval setting and preserve native restrictions |
| Nexus tool permission | Host evaluates the Nexus tool's policy and grant; native automatic approval does not grant Nexus access |
| User question | Preserve the actual question and typed answer contract; automatic approval must never invent an answer |

For a harness with native HTTP MCP support, extend the declarative template
and process configuration path in `harness_config.py`. The harness connects
directly to the Nexus Server MCP endpoint. Core does not implement a new MCP
server or relay. Scope credentials to the approved process and redact them
from output, logs, events, and public discovery.

For a harness without suitable MCP support, implement a native extension
using the typed, scoped backend in
[`native_action_bridge.py`](../src/nexus_connector_core/native_action_bridge.py).
Pi's [`pi_extension_resource.py`](../src/nexus_connector_core/pi_extension_resource.py)
and [`native_action_socket.py`](../src/nexus_connector_core/native_action_socket.py)
show the existing integration. Do not assume the Pi extension can load into
another harness. Messaging, context access, handoff claim/completion, and
runtime-input actions still execute through authorized host backends.

For native questions and approvals, retain the original request ID, hash,
method, parameters, session/turn, and generation. Extend the bridge and R4
request/decision classification where required. Answers must be validated
against that original request and translated into the harness's exact native
response shape; reject stale, replayed, mismatched, or malformed responses.
Do not invent multiple-choice or multi-select support absent from the native
protocol. See [R4 native approval and input](nxl-r4-development.md).

The host routes a question to the originating interlocutor. Nexus displays
operator questions in Meta-harness, or exposes an authorized question to the
recipient agent. An agent's answer uses the same validated input contract.
Core supplies the bridge and scope, not the operator UI or agent-to-agent
routing policy. Verify those consumer paths explicitly for the new adapter.

## 7. Test before qualifying a build

Start with a deterministic contained peer under `tests/fixtures/`. Use it
for protocol failures and race conditions, then run real harness campaigns
for each claimed version/platform/architecture. Synthetic peers establish
regressions, not production qualification.

| Area | Required cases and existing references |
| --- | --- |
| Registration/discovery | Lazy imports, unknown ID/platform refusal, duplicate installations, absent binary, version checks; `test_native_registry.py`, `test_passive_discovery.py`, `test_discovery_probe.py` |
| Identity/preparation | Changed executable/dependency/root, Unicode/spaces, concurrent workspace file creation; `test_profiles.py`, `test_workspace_launch_identity.py` |
| Configuration | Model/provider/effort mapping, invalid/unknown values, discovery failure, JSON round trip; `test_harness_settings.py`, `test_harness_configuration.py`, `test_configuration_file.py` |
| Protocol/output | Readiness, partial UTF-8/JSONL, truncation, delta/snapshot reconstruction, correlated start/terminal, duplicate/late events; `test_native_jsonl.py`, `test_event_ingest.py`, harness output-correlation tests |
| Runtime guarantees | Same-operation retry/conflict, pre-write refusal versus uncertain effect, expiry/revocation, concurrency, close/reopen/shutdown; `test_native_runtime_bridge.py`, `test_native_prewrite_adapters.py`, `test_native_close_outcome.py`, `test_r4_runtime_leases.py` |
| Questions/tools | Manual approval/denial, late answer, malformed answer, cancellation, custom choice, automatic tool approval without automatic human answers; `test_pi_native_inputs.py`, `test_codex_mcp_elicitation.py`, `test_r4_decision_bridge.py`, `test_native_action_bridge.py` |
| Packaging/consumers | Import isolation, bundled resources, installed wheel and both consumers; `test_wheel_import_audit.py`, `test_consumer_conformance.py` |

From an isolated development environment at the repository root, the basic
validation sequence is:

```sh
python -m pip install ".[test]"
python contracts/generate.py --check
python contracts/generate_r4.py --check
python -m pytest -q
python tools/build_artifacts.py
python tools/verify_wheel.py
```

Use the full packaging matrix in
[Core CI](../.github/workflows/core-ci.yml), including offline wheel/sdist
installation. The current main CI matrix covers Windows and Linux; a macOS
claim additionally needs actual macOS validation. Existing native probes
under `tools/` are references, not a universal new-adapter runner. Run them
only with an explicitly selected installation, approved account/workspace,
and understood provider usage.

Record real evidence under `plans/implementation/evidence/`: Core commit,
native version/build identity, OS/architecture, command/configuration,
exercised cases, sanitized results, and remaining gaps. Update the exact
qualification gates in `compatibility.py` only for demonstrated capabilities.
Conversation, controls, native input/approval, and attach support are not
interchangeable qualifications. Pi also illustrates why a dependency-aware
portable build identity may be required rather than a two-file fingerprint.

## 8. Deliver to Server and Connector

Review closed schemas in `contracts/`, generator sources, fixtures, and public
exports. If the change affects a wire shape or closed enum, update the source
and regenerate the bundle; do not hand-edit generated JSON or retrofit R3
hashes. Follow the [R4 development contract](nxl-r4-development.md).

Publish/build the new Core version using the repository's release process:
`tools/build_artifacts.py`, `tools/verify_wheel.py` and
`tools/validate_release.py`, with the protected workflows under
`.github/workflows/`. Update the `nexus-connector-core` dependency pin in
each consumer's `pyproject.toml` (for example the Nexus Connector
repository) and the Core-version compatibility checks, then install the
same artifact in Nexus Server and Nexus Connector. The catalog
feeds consumer choices, but host-specific version probes, credential mappings,
configuration reconstruction, and action wiring may still require updates.
Audit those paths instead of assuming a new catalog entry makes everything
work automatically.

Documentation is part of the delivery: record the adapter's migration entry
in [`adapters.md`](adapters.md), keep the qualification statements in
[`compatibility.md`](compatibility.md) limited to demonstrated capabilities,
and update this guide's references if the audit table or the interface above
changed.

Validate through the Nexus UI on both local and remote execution paths:

1. Discover and select the intended installation and login-directory hint.
2. Prepare folders, approve the connection, save native settings, and authorize
   execution with the intended scope.
3. Run the final connection test, confirm a real response, and close the test
   session. Configuration saved or request accepted is not connection verified.
4. Exercise private messages, broadcast, handoff delivery/claim/completion,
   and direct A-to-B messaging through the actual exposed Nexus tools.
5. Exercise manual and automatic Nexus tool approval, native harness approval,
   operator questions, and agent-to-agent answers independently.
6. Run concurrent A-to-C and B-to-C conversations under shared and per-sender
   host session policies; verify recipient routing and context isolation.
7. Check output completeness, delivery/read receipts, failed authentication,
   unavailable installation, timeout, disconnect/reconnect, and Execution log.

Do not mark unsupported or untested cells as successful. The integration is
ready when its declared capabilities match observed behavior, the installed
consumers use the new artifact, and each remaining limitation is explicit.
