# K04 event reader startup barrier — 2026-09-25

`LocalRuntimeCore.open()` previously scheduled its event-pump task and could
commit a `SUBMITTED` receipt before that task ran. An immediately following
native send could therefore precede the Core event reader. A deterministic
fake-native test reproduced the ordering failure.

The open effect now waits for the event pump to start before returning its
native ID. An immediate pump failure makes open raise
`EVENT_STREAM_UNAVAILABLE`; the operation kernel records `OUTCOME_UNKNOWN`
because native launch may already have happened, and the live binding remains
available for shutdown/reconciliation. Tests verify both the first-command
ordering and this immediate-failure path.

Windows source suite: 326 passed, 67 skipped. Ubuntu WSL2 source suite:
381 passed, 12 skipped, with the expected legacy Pi fault-injection thread
warning. Wheel/sdist build and clean-wheel import/resource verification pass.

This barrier only proves scheduling of the Core pump before open returns.
Copied adapters start their own pipe reader threads during native `start()`;
real provider/platform campaigns must separately qualify that those readers
are active and drain continuously. A reader that fails later still produces
the durable pump-failure event and blocks new submissions, but its earlier
open receipt is not retroactively rewritten.
