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
   The header review below confirms flavor 20's layout and indices. Establish
   which coalition membership is sufficient for ownership under all supported
   native scenarios before selecting a production tree key.
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

### ABI review for the next prototype

Apple's [private process header](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info_private.h)
defines flavor 20 as a structure containing the coalition-ID array and three
reserved 64-bit fields. Its [Mach coalition header](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/mach/coalition.h)
defines two types: resource at index 0 and jetsam at index 1. Thus the currently
documented structure is 40 bytes. The original probe allocates 64 bytes and
accepts any positive response length. A production implementation must validate
the expected response length, rather than treating a partial read as membership.
This is a private ABI dependency that needs explicit native version coverage.
The headers explain the indices; they do not prove that comparing both IDs is
the correct ownership guarantee. These sources were reviewed on 2026-10-02;
the report for `1975e88` remains unchanged and still describes its original code.

## Next native experiment: launchd and pipe transfer

The next launchd/pipe experiment is now available separately; use the commands
below before repeating the original scenarios. It does not change production
preflight or provider support.

```sh
git pull --ff-only origin feature/v0.2.0
python3 -I tools/macos_launchd_probe.py --run-native --domain user --output macos-launchd-user.json
python3 -I tools/macos_launchd_probe.py --run-native --domain gui --output macos-launchd-gui.json
```

Run in the Core checkout on the same Intel Mac. Record whether the shell is a
local terminal, SSH session or LaunchAgent context. Both JSON reports matter,
including failures: user/gui domain accessibility is part of the observation.
The program needs only Python's standard library, no package install or sudo.
It creates three unique temporary launchd jobs per invocation with generated
plists, `RunAtLoad=true`, `KeepAlive=false` and `launchctl bootstrap`, then uses
`bootout` and a follow-up query to inspect removal. It runs fixed Python fixtures
only, not provider binaries, credentials or workspace code.

The job transfers three native pipe descriptors over AF_UNIX `SCM_RIGHTS`.
The caller verifies stdin/stdout round trip, separate stderr, child/grandchild
descriptor hygiene and non-inheritable received descriptors. The guardian checks
the exact 40-byte coalition ABI and refuses either coalition type shared with
the caller or PID 1. An independently killable synthetic owner permits three
shutdown experiments: explicit cancel, owner SIGKILL while the observer keeps
the control socket open, and control-socket EOF. kqueue registration brackets
owner birth checks before native launch.

All native fixtures have alarms. The guardian reaps its fixed direct child; the
fixture reaps its own short-lived grandchild before acknowledging the round trip.
This experiment does **not** yet implement arbitrary coalition census, escaped
orphan cleanup, SIGSTOP/fork race handling, production Popen integration or slot
retention. The observer removes the job labels; autonomous label removal after
the entire observer/daemon crashes remains a separate acceptance item. Reports
retain `tree_stop_proven=false` and `containment_qualified=false` even on success.

Portable validation is in
`implementation/evidence/macos-launchd-probe-portable.json`: eight unittest cases,
five passes/three Unix-only skips on Windows and eight passes on WSL Python 3.12,
including actual fixture pipe transfer. Native launchd, coalition and kqueue
behavior remain unexecuted here. The Windows refusal JSON is retained separately.

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
