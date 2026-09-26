# Pi native extension artifact — 2026-09-25

The Core wheel/sdist now carry `pi_extension/index.js` plus a versioned
`package.json`. The extension is dependency-free JavaScript, so its reviewed
source is the build artifact itself: no transpiler, npm install, remote fetch,
or runtime download. `pi_extension_path()` resolves the installed resource for
Pi's explicit `--extension` option. The clean-wheel check verifies that both
resources are present in both artifacts and resolvable after installation.

The extension registers only `nexus_handoff_get`, `nexus_handoff_claim`, and
`nexus_handoff_complete`. Their closed JSON schemas and implementation send a
single bounded JSONL record over a loopback TCP socket with an exact action
name, operation/session/handoff IDs, capability ref and action-specific fields.
The host injects `NEXUS_NATIVE_ACTION_PORT`, `NEXUS_NATIVE_CAPABILITY_REF`,
and `NEXUS_NATIVE_SESSION_ID`; absent configuration fails closed. The address
is hard-coded to `127.0.0.1`, not model-configurable. The capability is
transport data, not a model-visible tool parameter. No HTTP client, MCP
endpoint or proxy is involved. `NativeActionSocketService` binds loopback
only, validates exact records, then invokes `ScopedNativeActionBridge` with
the host's current `ExecutionContext`. The trusted host still owns the
canonical backend and must provide its own capability issuance/revocation.
`PiRpcConnector` takes a typed `PiNativeActionLaunch`, adds the installed
extension through `--extension`, and gives only the owned Pi child the three
native-action environment values. The `CopiedAdapterFactory` accepts this
launch only from a trusted callback, after build qualification, and checks its
session and capability against the prepared launch. Arbitrary `NEXUS_*`
overrides remain denied.

Local Node tests exercise registration, fail-closed configuration, and each
structured call over a **real loopback socket** to the Python Core ingress
and an injected fake canonical backend. Negative tests cover duplicate/extra
fields, MCP envelope, wrong capability/session, changed authorization revision,
and an ambiguous claim outcome after the fake backend is invoked. This is
still **not** a real Pi installation or J17/TK-35 qualification; no live Pi
process or production host backend was used.
Pi version qualification, production host wiring/issuance, replay/failure
campaign, and multi-host tests remain pending.

Verification after the JSONL transport change: `pytest -q` reported
`246 passed, 66 skipped`; `python -m build --no-isolation` and the clean-wheel
resource/import verifier passed.

Protocol basis: official Pi
[extension documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
and [RPC documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md).
