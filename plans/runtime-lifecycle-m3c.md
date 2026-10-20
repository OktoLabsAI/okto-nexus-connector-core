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
release retain ownership. Finished workers are consumed in the same shutdown
call, allowing factory disposal without an extra shutdown request. Claimed
openings keep their original uncertain receipt; no native call is replayed.

Installed Windows campaign: **111 passed**, exit 0, including real disposable
processes failing before/after spawn, the actual Pi adapter with an injected
version-probe failure, retained stop/release workers, launch-controller fences,
settlement, shutdown resources and the runtime lifecycle regressions.

- Core wheel SHA256: `a24e21028e997cc5db3f1a55b179dd8e01d410fb7483ead9cb7350e1ca170398`
- Evidence: `build/failed-launch-m3c-final-installed/manifest.json`, `results.xml`.
- Manifest SHA256: `044a46b1d035590f395d6a2549c82a8e4e4cbc91b4b7b2e7462f45c8d23de321`
- JUnit SHA256: `5aab2372caa317fd38beb6ee732804404642f7a773a9f2e6d3ff0a4ea45944ed`
- Isolated interpreter; all installed Core package files compared with the wheel.
- Campaign: 20:28:27–20:28:41 UTC, 2026-10-16.

This proves recovery of the reproduced failure class, not the exact original
Pi CONFIG_ERROR subtype: the old live diagnostics discarded that detail. It
does not qualify Linux/macOS recovery or complete M3. Consumer/UI qualification
and live installation are tracked in the Nexus canonical ledger.
