# M3h — Bounded parallel passive discovery

2026-10-17. Core 0.0.12 / feature/v0.0.12.

Discover Codex, Pi and Claude concurrently with at most three submitted readers
per pass. Each reader inherits the caller's cancellation context. The caller
joins every reader before returning, including cancellation and failure paths.
Catalog order, full-content identity checks, trust rules and duplicate-evidence
drift refusal remain unchanged. No harness process is executed by discovery.

The snapshot is still complete and atomic. This is not independent per-harness
publication/readiness: a slow observation still delays publication of the full
snapshot. That contract change remains open in Nexus L14/M3.

Validation on Windows: 22 source cases passed; **59 installed cases passed**.
Both campaigns skipped 18 POSIX-only cases; Linux/macOS are not qualified here.
Tests prove simultaneous entry, bounded submissions, cancellation propagation,
join on failure, deterministic output, trust boundaries and existing discovery
and version-probe contracts. Installed runner verified all 156 package files.

Passive reads of the actual three installed harnesses, alternating serial /
parallel / parallel / serial in one isolated installed interpreter, measured
21.94 / 10.74 / 13.94 / 21.75 seconds. All four complete observations had the same
content digest. These are four local samples under variable machine load, not a
startup SLA or a provider execution benchmark. Nexus records the measurements
in `plans/runtime_lifecycle/m3h-results.json`.

Wheel SHA256: `e95a306637c784dedd8e07215e957cfc7f343116bf4517400c5d46bfde605917`.
Evidence: `build/runtime-lifecycle-m3h-installed/{manifest.json,results.xml}`.
Consumers retain their Core 0.0.12 pin and update the vendored development wheel.
Global deployment and the full M3/UI-A gate remain pending.
