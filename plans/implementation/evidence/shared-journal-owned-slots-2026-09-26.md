# Shared-journal owned slots — 2026-09-26

The prior `max_owned_sessions` limit was process-local. Two
`LocalRuntimeCore` instances using the same SQLite journal could each admit
their full budget. The journal now transactionally reserves managed-launch
slots after possible-effect admission and before the native factory call.
`JournalLimits.max_owned_slots` defaults to eight; the local runtime default
`max_owned_sessions` is also eight. Connections to one journal file must use
the same durable slot policy or fail with `PROFILE_DRIFT`.

The reservation is keyed to the original session/open claim, cannot be
reused, and survives process exit/reopen. It is released only on a proven
prelaunch refusal or after the live native binding reports `STOPPED`. Ambiguous
launch/close, cancellation and absent stop evidence keep the slot. A full
shared budget safely records the new open as a pre-native `FAILED` receipt,
without invoking the factory; that failed session ID remains claimed.
Fault injection confirms claim/effect prerequisites and transaction rollback.
Two independent runtime instances with one SQLite file cannot exceed one
configured slot; an uncertain open pins it through reopen. Three independent
Python processes racing for two slots produced exactly two reservations and
one `CAPACITY_EXCEEDED`, retained after abrupt process exits. The reusable
Journal-port and restart conformance kits now require reserve/release and
detect an adapter that silently drops reservations.

The first concurrent-start WSL2/Python 3.11 campaign exposed a transient
`SQLITE_BUSY` at `PRAGMA journal_mode=WAL`. Journal initialization now retries
only `SQLITE_BUSY/LOCKED` for at most five seconds, verifies WAL mode and
fails closed on other errors. Ten repeated WSL2/Python 3.11 multiprocess
campaigns then passed. The 67 focused slot/runtime/conformance/docs tests
passed on local Windows/WSL2 × Python 3.11–3.13.

Full Python 3.13 suites passed Windows 562/73 and WSL2 621/14
(passed/skipped), with the expected legacy Pi injected-failure warning.
Normalized Windows/WSL2 artifacts matched byte-for-byte: wheel SHA-256
`1c67f6868a7b2c888a882a93b1d7a59b59506323050827f54a543ee741e2847d`,
sdist SHA-256
`341261bc4124bd9873cb8c3622f840c79ea4cea1f62ced7ddda297d079dd2c51`.
Strict Twine, development-mode release validation (`publishable:false`),
clean-wheel import/embedded/remote consumer smokes, and offline wheel/sdist
installation/resource checks on all six local OS/Python combinations passed
for this exact pair.

This is a **shared-journal** cap, not a host-wide or installation-wide cap
when hosts use separate journal files. The journal cannot itself verify the
native stop assertion supplied by its trusted runtime caller. A crash can
conservatively strand a slot; safe recovery needs independent ownership/
containment proof, not a PID-only or timeout-based release. Real Server/
Connector host adapters and provider campaigns remain open.
