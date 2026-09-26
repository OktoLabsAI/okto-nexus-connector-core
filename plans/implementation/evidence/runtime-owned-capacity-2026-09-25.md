# K04 local owned-session capacity — 2026-09-25

`LocalRuntimeCore` now has a positive `max_owned_sessions` ceiling (default
32) in addition to the concurrent-open ceiling. The local count includes
reserved opens, sessions whose stop has not been observed, and opens where
the native factory entered the effect window but failed without returning a
session handle. A second open is refused before journal admission or native
launch with retry-safe `CAPACITY_EXCEEDED`. A session slot is released only
after `close()` observes `STOPPED`; an uncertain close retains it. An
ambiguous open without a handle retains a slot and appears as `unknown` in
the shutdown report.

The kernel now accepts an explicitly retry-safe, no-possible-effect
`CoreError` from a trusted effect as a durable `FAILED`/not-sent receipt.
Prelaunch mode/version/environment gates in the Core-owned copied-adapter
factory mark those rejections retry-safe. This avoids burning an owned slot
for a proven prelaunch refusal, while unexpected factory errors remain
`OUTCOME_UNKNOWN` and keep the slot. Tests cover active, pending, safely
rejected and ambiguous opens plus uncertain close on Windows and WSL2.

Full Windows source suite: 333 passed, 67 skipped. Ubuntu WSL2 source suite:
388 passed, 12 skipped, with one expected legacy Pi fault-injection thread
warning. Wheel/sdist build and clean-wheel import/resource verification pass.

This is a **per-runtime owned-session** budget, not a host-wide physical
process-tree count. A factory may own multiple descendants; other runtime
instances have separate counters. Unknown no-handle slots are intentionally
not released in that runtime without proof, but the count is not persisted
across Core recreation. Native-call timeout accounting, persisted process
ownership and host-wide reconciliation remain K04 gates.
