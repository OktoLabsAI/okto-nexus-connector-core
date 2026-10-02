# Native macOS Intel implementation and manual validation

On 2026-10-02 the user authorized development here and offered to update and
run the code on the same Intel/x86_64 Mac as Connector issue #1: macOS 26.4.1,
Python 3.12.4. This resolves the initial target question for an Intel prototype.
It does not accept a weaker process ownership contract, qualify Apple Silicon,
or replace the later user-operated independent-host acceptance. CI remains
deferred at the user's request.

## Native scenario evidence received — 2026-10-02

Core issue #1, updated at `2026-10-02T14:09:23Z`, now contains a user-operated
Intel Mac report. The exact JSON and issue snapshot are retained under
`implementation/evidence/macos-intel-scenarios-reported-20261002.json` and
`implementation/evidence/macos-intel-issue-1-20261002.json`, with provenance in
`implementation/evidence/macos-intel-scenarios-source-20261002.json`.
The extended script hash is
`a318878f108c2c1099cf40ed748420df65054109d3cef1cb5b82ab85235f0c1b`.
The user subsequently published `1975e88`, incorporated by fast-forward. Its
Git blob SHA-256 exactly matches the reported script hash, and the committed
report is structurally identical to the issue JSON. Windows checkout CRLF bytes
have a different hash; provenance was checked against the Git blob. Syntax was
checked locally; the native scenarios were run by the user on the Mac.

The report disproves parent-based tracking: fast double-fork plus `setsid`
escaped both event-driven tracking and roughly 2 ms polling in 24/24 runs.
Do not implement that tracker as an ownership guarantee. Dedicated launchd job
coalition membership found 10/10 escaped orphans and the coalition kill pass
left zero alive. Removing the launchd job alone left all ten alive. Final probe
cleanup reports no surviving fixtures or registered probe labels.

Owner `NOTE_EXIT` still arrived when an inherited pipe writer prevented EOF.
Use owner birth verification and kqueue exit registration as the primary death
signal; a launchd guardian already has PID 1 as parent, so reparenting is not a
death signal. The reported 1.5 s cleanup delay was deliberate probe collection
time. No provider ran and `containment_qualified` remains false.

### Revised implementation sequence

1. The exact extended probe is incorporated and its coalition scenario reviewed.
   It matches the pair of resource/jetsam IDs, accepts any positive ABI response
   length, and tests the known orphan's survival after a bounded kill loop.
   These are diagnostic observations, not a complete production stop proof.
   Confirm the flavor-20 ABI and coalition type against Apple's headers; do not
   infer which of the two reported coalition IDs establishes ownership.
2. Prototype a unique per-session launchd guardian job using a generated plist,
   `KeepAlive=false`, and `launchctl bootstrap`. Test user/gui domains including
   SSH and LaunchAgent ownership. Refuse caller/shared/launchd coalitions before
   starting a provider. Never treat `launchctl remove` as a stop proof.
3. Validate native stdin/stdout/stderr transfer over AF_UNIX `SCM_RIGHTS`, owner
   death including leaked liveness descriptors, and cleanup of job labels on
   normal stop, crash and failed startup.
4. Implement bounded coalition census with birth and coalition revalidation
   before signaling, excluding the guardian itself. Incomplete scans, permission
   failures and overflow must not count as an empty tree. Validate SIGSTOP/fork
   races and the proposed two-empty-census stop condition before emitting `D`.
   The measured verify/signal window does not eliminate PID reuse races.
5. Keep production preflight unsupported until ownership is qualified. Passive
   preflight must execute no provider wrapper; successful ABI checks alone do
   not qualify containment. Keep process-count limits observability-only.
6. Run at least 100 fast double-fork/setsid cases with zero leaks, owner SIGKILL,
   cancellation escalation, descriptor hygiene, shared-coalition refusal,
   64-child census/overflow, and 32-slot retention until proven stop. Then run
   provider and integrated acceptance separately.

An explicit contract decision and native evidence remain necessary for requests
to external launchd/XPC services outside the runtime coalition. This report does
not authorize weakening ownership or establish that two empty snapshots prove
termination under every race. Apple Silicon, other macOS versions, hosted CI,
provider qualification and independent-host acceptance remain uncovered.

## Original primitive probe (historical first step)

From an updated `okto-nexus-connector-core` checkout on `feature/v0.2.0`:

```sh
python3 -I tools/macos_containment_probe.py --run-native --output macos-containment-report.json
```

This uses only the Python standard library and needs neither package installation
nor sudo. It launches one short-lived isolated Python fixture, which forks and
reaps an immediately exiting child. No provider, credential, workspace or system
service is used. The fixture has an alarm and bounded parent waits. Send back
the generated JSON, including a failure report if the command returns nonzero.

The report checks the `proc_pidinfo` ABI and stable process birth, boot identity
(hashed), a private process group, and `kqueue` fork/exit notifications registered
before the fixture is released. It includes the script hash and OS/Python/CPU.
`PRIMITIVES_OBSERVED` is only evidence of these mechanisms. It does **not** prove
arbitrary descendant tracking, owner-death cleanup, race-free signaling, a full
tree-stop proof, or provider qualification. Non-Mac hosts refuse the test and
report `containment_qualified: false`; production preflight remains unchanged.

Local verification: syntax and 136-byte ABI layout/start-time offset checked on
Windows Python 3.13.1; the non-Mac refusal report is retained in
`implementation/evidence/macos-probe-windows-refusal.json`. Native scenario
results have subsequently arrived as recorded above.

## Implementation acceptance still required

1. Review native evidence and design ownership of escaped descendants. A census
   that momentarily becomes empty is not sufficient proof of tree termination.
   Re-reading a PID's birth immediately before signaling alone does not eliminate
   the race between that read and the signal. Resolve both before qualifying.
2. Implement the guardian, owner-liveness channel, cancellation and stop-proof
   channel, birth observations, capacity retention and bounded census. Keep
   unsupported preflight until the ownership guarantees have native evidence.
3. Run native owner-crash, fork/exec/setsid escape, PID reuse, pipe inheritance,
   cancellation, shutdown, census overflow and capacity tests on this Intel Mac.
4. Qualify Claude, Codex and Pi independently using installed artifacts, real
   turns and recovery. Then validate Connector IPC, service lifecycle and Nexus
   UI/CLI integration. Update support claims from those results only.

Apple's [process ABI](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info.h)
defines the queried structure. Its [event header](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/event.h)
explicitly marks automatic fork tracking (`NOTE_TRACK`/`NOTE_CHILD`) unsupported;
the diagnostic does not use it. These are design inputs, not native test evidence.

Tracking: [Connector #1](https://github.com/OktoLabsAI/okto-nexus-connector/issues/1)
and [Core #1](https://github.com/OktoLabsAI/okto-nexus-connector-core/issues/1).
