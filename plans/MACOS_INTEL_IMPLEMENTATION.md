# Native macOS Intel implementation and manual validation

On 2026-10-02 the user authorized development here and offered to update and
run the code on the same Intel/x86_64 Mac as Connector issue #1: macOS 26.4.1,
Python 3.12.4. This resolves the initial target question for an Intel prototype.
It does not accept a weaker process ownership contract, qualify Apple Silicon,
or replace the later user-operated independent-host acceptance. CI remains
deferred at the user's request.

## First native evidence

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
`implementation/evidence/macos-probe-windows-refusal.json`. No native Mac result
exists yet.

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
