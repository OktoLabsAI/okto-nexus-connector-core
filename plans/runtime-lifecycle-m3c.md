# M3c — Contain failed launches under the original owner

2026-10-16. Core 0.0.12 / feature/v0.0.12.

The live M2e Nexus campaign found Pi openings with durable CLAIMED launches,
OUTCOME_UNKNOWN receipts and no process birth records. LocalRuntimeCore retained
their capacity but shutdown never attempted containment when the native factory
had failed without returning an adapter handle. Restart-only host recovery was
insufficient for that same-owner failure.

Shutdown now supervises one recovery worker per uncertain planned launch. It
requires the runtime to be shutting down, the exact original launch identity,
no active opening/binding/late handle, producer exclusion and durable fencing.
Only a confirmed stopped container permits the existing durable-release path.
Slow workers survive observation timeout; unknown evidence and failed/blocked
release retain ownership. Factory disposal waits for these workers. Claimed
openings keep their original uncertain receipt; no native call is replayed.

Installed Windows campaign: **111 passed**, exit 0, including real disposable
processes failing before/after spawn, the actual Pi adapter with an injected
version-probe failure, retained stop/release workers, launch-controller fences,
settlement, shutdown resources and the runtime lifecycle regressions.

- Core wheel SHA256: `18d2132714cbeee09577b63ff4c7859eb878eb788a4c442e5a1c3e3b467466fd`
- Evidence: `build/failed-launch-m3c-installed/manifest.json`, `results.xml`.
- Manifest SHA256: `f90e4f3021f24027ed1c66dfc4f0977ffef007b4ccf029a72a7f1a6accd6a0c4`
- JUnit SHA256: `9a908483b17c62d1c85c309822be30a450c53fa5dd58a989ae938532b405f7f0`
- Isolated interpreter; all installed Core package files compared with the wheel.
- Campaign: 20:22:28–20:22:57 UTC, 2026-10-16.

This proves recovery of the reproduced failure class, not the exact original
Pi CONFIG_ERROR subtype: the old live diagnostics discarded that detail. It
does not qualify Linux/macOS recovery or complete M3. Consumer/UI qualification
and live installation are tracked in the Nexus canonical ledger.
