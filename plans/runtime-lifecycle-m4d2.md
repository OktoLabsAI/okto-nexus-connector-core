# M4d2 — Historical association for released pre-open capacity

The Core ledger can resolve an exact released `OwnedSlotState` to the canonical
opening that consumed its provisional capacity slot. Placeholder identities stay
inside the storage adapter. This is a read-only association, never permission to
release resources, replay work or claim that a native process exited.

The observed release flag must match storage. A formerly occupied observation
does not acquire release authority, and a fabricated released observation cannot
match an occupied slot. Namespace, reservation and unstarted-consumption checks
remain mandatory. The existing occupied-slot lookup retains its behavior.

Qualification on Windows, isolated interpreter and installed Core 0.0.12:
**38 tests passed** in 23.19 seconds. The campaign covers exact lookup, capacity
ledger, cancellation, unstarted release and recovery. Both current and opaque
historical reservation identities are tested before/after release and reopen.
No native provider or physical remote-host qualification is claimed here.

Wheel SHA256: `fffcfad6a82a67fb4b9cc4b25b0718a3c3e30bf119dde71ee07dcb062b814898`.
Evidence: `build/runtime-lifecycle-m4d2-installed/{manifest.json,results.xml}`.
The installed runner verifies every package file against that wheel. Nexus and
Connector consume the same development artifact; no PyPI release or global
installation is part of this checkpoint. Full M4/M5 remain open in the Nexus plan.
