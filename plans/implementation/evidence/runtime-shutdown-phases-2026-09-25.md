# K04 shutdown drain and interrupt phases — 2026-09-25

On shutdown, the Core refuses new work and lets a known active native turn
settle during `drain_seconds`. `CopiedAdapterSession.active_turn()` reports a
sent turn until a correlated terminal event clears it; an in-flight normal
send also keeps the drain pending. If the turn remains active, the Core admits
a deterministic technical `runtime.shutdown_interrupt` operation to the
SQLite journal as `SUBMISSION_STARTED` before sending the native interrupt.
An adapter-proven no-write refusal becomes retry-safe `FAILED`; a returned
send becomes `SUBMITTED`, not completed. The Core then observes for up to
`interrupt_seconds` and starts native close. A pending interrupt or close
can outlive the caller's total observation budget; the report is `unknown`
and the owned slot remains reserved until stop is observed.

Synthetic tests cover a turn settling during drain without interrupt, a
persisting turn with journal-before-send, proven no-write refusal, and an
interrupt stalled past the caller deadline with late cleanup. Native sessions
without the optional active-turn observation retain the earlier best-effort
close path after in-flight sends finish. A separate managed-tree force request
now exists and is described in `runtime-force-containment-2026-09-25.md`.
No real provider/platform shutdown campaign has run. K04.4 and TK-20
therefore remain incomplete.
