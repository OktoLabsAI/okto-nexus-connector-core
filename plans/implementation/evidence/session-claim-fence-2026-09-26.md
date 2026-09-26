# K04/K10 durable session-claim fence - 2026-09-26

Previously, `LocalRuntimeCore.open` rejected a duplicate session ID only
against its process-local maps. After restart, a different operation ID could
use the same Server/executor/session ID and open another native process,
despite the first open's durable journal history. The reproducing runtime
test demonstrated this failure before the fix.

SQLite admission now has an optional `claim_session` flag used by
`runtime.open`. A `session_claims` row keyed by Server/executor/session is
inserted in the same `BEGIN IMMEDIATE` transaction as the open operation.
The exact duplicate operation remains idempotent; a different operation
cannot reuse the session ID after close, safe failure, or restart. A fresh
session ID is required for a new open attempt. Migration backfills claims
conservatively from preexisting operation rows. Two SQLite connections
competing for one claim admit only one; an injected failure of the operation
insert rolls back the claim as well. Another Server namespace can use the
same local session ID.

The Journal port and reusable conformance kit now include this semantic;
a host adapter that ignores `claim_session` is detected by the kit. This
does not establish physical process ownership, lease continuity, or a full
reconnect/takeover protocol after restart. The actual Server journal adapter
has not run the kit.

Focused session-claim, journal-conformance and runtime tests passed on
Windows/WSL2 Python 3.11-3.13. Full Python 3.13 suites passed: Windows
499 passed/73 skipped, WSL2 558 passed/14 skipped, each with the expected
injected legacy Pi thread warning.

Normalized Windows/WSL2 builds matched: wheel SHA-256
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`,
sdist SHA-256
`529886b5f79907d746270db8a3e55f10b2665f63944f5b3c81e717345de7fc78`.
Strict Twine, clean-wheel consumers, Windows offline wheel/sdist installation
and development-mode release validation passed; `publishable` remains false.

The contention campaign was strengthened with two independent Python
processes released by one parent barrier. Exactly one open claim and one
operation row survived in the shared SQLite journal; the losing process
received `SESSION_CONFLICT`. This focused case passed on Windows and WSL2
Python 3.11-3.13. The final full Python 3.13 suites passed at Windows
500 passed/73 skipped and WSL2 559 passed/14 skipped, with the expected
injected Pi warning. The rebuilt wheel remained
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`;
the matching Windows/WSL2 sdist containing the new peer is SHA-256
`1b0a6ddedf0893ad5c934da2c8a6b00b7731b100dc61a2df63941314a75584bc`.
Strict Twine, development release validation (`publishable:false`) and
Windows offline wheel/sdist installation passed for this pair. The wheel
bytes were unchanged from the preceding clean-wheel consumer verification.
