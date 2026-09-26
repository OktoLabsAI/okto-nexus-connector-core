# K04 urgent control during a slow native send — 2026-09-25

`LocalRuntimeCore._send` formerly held its runtime-wide lock across the
adapter's awaited `send`. A blocked `turn.submit` therefore also blocked an
urgent `turn.interrupt`. A deterministic test first reproduced that failure.

Normal sends and urgent controls now use separate per-session locks, with the
runtime-wide lock held only for state/admission checks. Close, shutdown and
lease-expiry close acquire both session locks before releasing native
ownership. The admission checks are repeated after waiting for a session
lock, so a queued operation cannot bypass a close or shutdown. The SQLite
journal remains the atomic duplicate-admission authority.

`open()` also formerly held the runtime-wide lock across preparation,
verification and the native factory launch. It now reserves only its target
session while doing that work. Concurrent opens for the same session are
rejected; shutdown waits for all reserved opens to finish before snapshotting
and closing sessions, so a launch already in progress cannot escape cleanup.
Cancellation of an in-flight open releases the reservation and leaves an
`OUTCOME_UNKNOWN` receipt rather than a false no-effect conclusion.

`tests/test_runtime.py` verifies that an interrupt is submitted while a fake
native submit is deliberately pending, that an explicit close waits for the
pending write without preventing the interrupt, and that a slow launch of a
different session does not block that interrupt or escape shutdown. The full source suites
pass on Windows (324 passed, 67 skipped) and Ubuntu WSL2 (379 passed, 12
skipped; one expected legacy Pi fault-injection thread warning). Wheel/sdist
build and clean-wheel import/resource verification pass.

This does not establish finite shutdown for a native call that never returns,
provider-specific concurrent control safety, or a total live/uncertain
process-tree limit. Those remain K04/K05–K08 qualification work.
