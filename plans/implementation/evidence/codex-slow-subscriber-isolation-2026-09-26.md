# K04/K10 Codex slow-subscriber isolation — 2026-09-26

The Core-owned Codex adapter shares one native app-server process among
sessions. Previously, overflow of any transient subscriber queue killed that
shared process, interrupting unrelated healthy sessions. The adapter now
detaches only the overflowed subscriber. Its bounded queue still drains its
retained prefix and raises `NativeEventOverflow`; the Core runtime pump treats
that as an event-stream fault for the affected session, journals a technical
fault when possible, blocks new admissions there, and retains ownership for
explicit close/reconcile. It never fabricates a successful terminal.

A scripted Codex peer opened noisy and quiet sessions in one process. A slow
subscriber for the noisy session exceeded its 128-event queue, received the
explicit gap, and was detached. The process remained alive and the quiet
session subsequently completed a real scripted turn. A separate Core-runtime
test injected the same overflow into one native binding and verified that a
second binding's event still reached the journal while only the first was
marked faulted. Both focused cases passed on Windows and WSL2 Python 3.13.

A follow-up process campaign emitted 140 delta frames through the fake Codex
child's actual stdout, rather than calling the adapter event method directly.
It reproduced the slow-subscriber gap and preserved the quiet session's
turn. In a second held-turn case, the quiet session still sent a targeted
`turn/interrupt` RPC and observed `turn/completed(interrupted)` after the
other session's stdout flood. These two peer cases passed on Windows/WSL2
Python 3.13; the existing runtime fault-isolation test also passed.

This is an isolation mechanism and a small process-level campaign, not a
sustained provider load test. A faulted session may still have an owned native
effect in flight; it is not freed or retried automatically. Global history
pressure, disk-full durability, many bindings and real-provider urgent
control behavior remain open for TK-40.

The two stdout-flood peer cases also passed on Windows and WSL2 with Python
3.11 and 3.12. The full Python 3.13 suites including the new urgent-control
case passed: Windows 477 passed/73 skipped and WSL2 536 passed/14 skipped,
each with the expected injected legacy Pi thread warning.

The post-test artifact pair matched byte-for-byte across Windows and WSL2:
wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`8d41b67f41baf8b8a45f28c58a74570e11f8ec84c2fe2701ba5cab78106bb3db`.
Strict Twine, clean-wheel embedded/remote consumers, development-mode release
validation (`publishable:false`) and Windows offline wheel/sdist installation
passed for this pair. The wheel stayed unchanged; the sdist includes the
new test and scripted native peer.

Windows/WSL2 Python 3.13 builds matched byte-for-byte: wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`2fbff8ba154c08c068a0585dd9cc5f39d6660590edcb30ad5ccc8c7518b45da6`.
Strict Twine and development-mode release validation passed;
`publishable` remains false.
The stable full Python 3.13 suites passed: Windows 476 passed/73 skipped and
WSL2 535 passed/14 skipped, each with the expected injected legacy Pi thread
warning. Windows offline wheel/sdist installation and clean-wheel embedded
and remote consumer smokes passed for this artifact pair.

The next process-level fairness case drove 2,200 native delta frames through
the child stdout, exceeding the shared 2,048-item transient replay window.
The noisy session's replay expired explicitly, while the quiet session's
held-turn replay remained available and its targeted `turn/interrupt` still
completed as interrupted. This passed on Windows and WSL2 with Python
3.11-3.13. The full Python 3.13 suites passed at Windows 478 passed/73
skipped and WSL2 537 passed/14 skipped, with the expected injected Pi warning.
This tests row pressure in one scripted shared process, not byte pressure,
sustained real-provider load, or the complete TK-40 scenario.

The matching Windows/WSL2 artifact pair for this test revision is wheel
SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`
and sdist SHA-256
`1ad6d9ea0c7aa74e429ed677145f963fda9e6bc6c519d6a770d7cb6cd12620b5`.
Strict Twine, clean-wheel consumers, development-mode release validation
(`publishable:false`), and Windows offline wheel/sdist installation passed.

Multi-session byte pressure exposed a real Core history defect: global
eviction removed the oldest event even when it belonged to a quiet session
with a tiny replay footprint. The Core-owned `NativeEventHistory` now evicts
the oldest event from the session currently holding the most bytes (or items,
for row pressure), latching replay expiration on that session. Bounded
unit cases reproduce the old failure and prove quiet replay retention for
both global byte and item caps. In a scripted Codex process, six noisy
sessions each emitted thirteen 80,000-character deltas over stdout; the
shared 4 MiB history cap held, noisy replay expired explicitly, and a quiet
held turn retained replay and completed a targeted interrupt. These focused
cases passed on Windows/WSL2 Python 3.11-3.13. The full Python 3.13 suites
passed at Windows 481 passed/73 skipped and WSL2 540 passed/14 skipped,
with the expected injected Pi warning. This is bounded synthetic evidence,
not sustained real-provider fairness qualification.

The matching Windows/WSL2 artifact pair for the Core code fix is wheel
SHA-256
`360b0b02df671230dc4ede62a31b8bd801c36c64b4e3eb3c610320c31b11d562`
and sdist SHA-256
`e60817cec8caf884f1d19e47fce006dc18a343460638598aa1b5b40d1ed758bc`.
Strict Twine, clean-wheel consumers, development-mode release validation
(`publishable:false`) and Windows offline wheel/sdist installation passed.

A follow-up global-byte preflight covers one incoming frame that is larger
than every retained session footprint. Previously, making room could erase
multiple small sessions' replay. The Core history now refuses to retain that
frame before global eviction, marks only its session's replay expired, and
leaves live fanout to the adapter's independent subscriber path. The
reproducing unit test failed against the old policy and passed after the
change on Windows/WSL2 Python 3.11-3.13. The full Python 3.13 suites passed
at Windows 482 passed/73 skipped and WSL2 541 passed/14 skipped, with the
expected injected Pi warning. The Codex 64-thread-attempt connection limit
also makes a 65th distinct replay tombstone unreachable in that adapter;
no tombstone behavior was changed on this evidence.

The matching Windows/WSL2 artifact pair is wheel SHA-256
`43c78dfae685052830df647df3b7afdb64d318e322009ee4f0fc79bc6b251915`
and sdist SHA-256
`8378660e9d38e94b8ad19b5df51f443a3895da4de5ffd217d18814884c58d7c9`.
Strict Twine, clean-wheel consumers, development-mode release validation
(`publishable:false`) and Windows offline wheel/sdist installation passed.

A direct Codex-adapter fanout test now also exercises the preflight rejection:
with two small replays retained, a large event was refused from transient
history, reached an already registered live subscriber, left both small
replays intact, and did not kill the native peer. It passed on Windows/WSL2
Python 3.11-3.13. The rebuilt wheel and sdist were byte-identical to the
previous pair (this test file is not in either archive); development-mode
release validation passed again. The WSL2 full Python 3.13 suite passed at
542 passed/14 skipped. The first concurrent Windows full run had one failure
in the unrelated Pi local-socket test; that case passed alone, and a repeat
Windows full run passed at 483 passed/73 skipped. Both full runs retained the
expected injected legacy Pi thread warning. The single transient failure
was not attributed to a root cause and does not establish flake-free CI.
Twenty additional isolated repetitions of the Pi local-socket case passed;
the initial failure remains unrooted.
