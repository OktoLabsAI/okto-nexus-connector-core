# M7a — Defer duplicate content hash to the open boundary

Date: 2026-10-17. Branch: `feature/v0.0.12`. No global rollout.

Read-only profiling against the real Pi 0.87.1 installation found a 14,097
entry dependency closure. A full content identity took 13.185 seconds in
one run. `LocalRuntimeCore.prepare` and `LocalRuntimeCore.open` each called
`prepare_launch`, which recomputed that identity for the same candidate.

The runtime's non-effectful `prepare` now defers only the full content hash.
It still checks the selected path fingerprint, workspace and profile. The
admitted `open` retains the complete `prepare_launch` revalidation before
slot reservation, journal admission or native spawn; direct callers of
`prepare_launch` retain its full default validation. There is no time-based
cache or acceptance of a changed artifact at the effect boundary.

The focused tests prove no full hash during runtime prepare, one full hash
during open, and refusal of changed content before the native factory is
called, even if a path-bound observation is stale. The direct API drift test
still rejects during prepare. Source regression: 88 tests passed across
runtime, profiles and build identity. Isolated installed wheel: 11 selected
cases passed, including the Pi lease-renewal regression from M3o. Wheel
SHA-256: `f0d6c9141ce59c04e01c419711b2b1e40f026ff99ba79c88c157f95da36ca457`.

With the installed wheel and a warm filesystem cache, the same real Pi
candidate's `prepare_launch` took 0.651 seconds without the duplicate full
hash and 8.300 seconds with it. This is a single local comparison, not a
production p50/p95. The open path still pays the full identity cost, so M7
remains open for per-frontier tracing, concurrent startup/pool qualification
and real UI gate UI-B. Nexus and Connector vendor this exact wheel; global
Nexus generation 73 remains unchanged.
