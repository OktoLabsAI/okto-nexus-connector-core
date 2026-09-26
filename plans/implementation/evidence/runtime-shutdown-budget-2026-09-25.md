# K04 bounded shutdown observation — 2026-09-25

`LocalRuntimeCore.shutdown()` validates finite, nonnegative drain and interrupt
windows and uses their sum as a monotonic observation deadline. It first stops
new admission, waits only until that deadline for in-flight opens, then starts
one close task per known session. Pending opens, sends and closes are reported
`unknown` without cancellation, fabricated stop evidence or capacity release.
Independent session close tasks let a fast session finish while another native
call stalls. A subsequent shutdown reuses an unfinished close task rather than
starting a duplicate native close. If an open completes after the first report,
its `finally` schedules Core-owned cleanup; the slot stays reserved until stop
is observed.

Synthetic tests hold native send, close and open calls across a 40 ms shutdown
budget, then release them and verify the eventual close/ownership state. These
tests prove the local facade's observation and bookkeeping, not a bound on the
native call or process lifetime. A separate synthetic phase test now covers
drain and journaled interrupt; force remains unqualified. Process ownership
is not persisted across restart.

Public `runtime.close()` and the lease-expiry watchdog also release the
runtime-wide state lock before awaiting native close. Both retain the two
per-session command locks, so shutdown may time out and report `unknown`
without admitting another command to that same session. A closing session
rejects lease renewal. Synthetic tests hold each close path pending, inspect
ownership and complete a short-budget shutdown before allowing native stop.
