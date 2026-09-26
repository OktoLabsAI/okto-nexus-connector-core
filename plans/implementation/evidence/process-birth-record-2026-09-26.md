# K04/TK-17 historical owned-process birth record - 2026-09-26

The Core-owned Windows Job Object and Linux guardian backends now expose a
birth identity read from their exact process handle/container: Windows
`GetProcessTimes` creation FILETIME, or Linux boot ID plus the guardian's
`/proc/<pid>/stat` start tick. Plain subprocesses cannot produce this
Core-owned evidence. Two successive real owned launches on Windows and WSL2
produced distinct PID/birth-token pairs; a repeated read of one handle was
stable. Attach targets do not use this path.

During `runtime.open`, the Core bridge snapshots the owned container and
stores one immutable record in its SQLite technical journal under the
original Server/executor/session claim and opening operation ID. The write
requires an admitted claim and possible-effect marker. Identical replay is
idempotent; changed birth evidence or operation ID conflicts. Reopening the
journal preserves the record and makes it available through
`RuntimeCore.process_birth`; `inspect` still reports `unknown` ownership when
there is no process-local binding. Journal insert failure rolls back without
a phantom record. An injected birth-write failure after native open leaves
the operation `OUTCOME_UNKNOWN` and the live binding owned; it cannot return
a successful open receipt. The Journal conformance and reopen kits exercise
this port behavior, but the actual Server adapter has not run them.

Focused process/journal/runtime/docs tests passed in all six local
Windows/WSL2 × Python 3.11–3.13 environments (65 each). Full Python 3.13
suites passed: Windows 538 passed/73 skipped; WSL2 597 passed/14 skipped.
Both emitted only the expected legacy Pi test's injected thread warning.

Normalized Windows/WSL2 artifacts matched byte-for-byte: wheel SHA-256
`01b315cf82881f55eb7349511bbe5bedb7a88e41c7fe39b4de6e92672ac26ced`,
sdist SHA-256
`84adc190d7ec6139443ccd8714d08cd22f5bab91bf15560918f6f4cc43e7e255`.
Strict Twine, clean-wheel embedded/remote consumer smokes, and offline
wheel/sdist installation/resource checks passed in all six local
Windows/WSL2 × Python 3.11–3.13 environments. Development release
validation returned `publishable:false`; no publication was attempted.

This is historical diagnostic evidence only. A process can exit, its PID
can be reused, and a crash can occur between spawn and recording. Neither
the birth record nor a persisted claim/lease authorizes signaling a PID,
reattachment, or takeover after restart. Full process-ownership recovery,
host-wide physical limits, the real Server adapter and broader OS/provider
qualification remain open.

An additional end-to-end synthetic factory test now injects a Codex-shaped
connector into the Core-owned `CopiedAdapterFactory`. Its `start` method
creates a real contained child through `spawn_owned_process`; public
`LocalRuntimeCore.open` then obtains the child's actual OS birth token through
`CopiedAdapterSession`, persists it and returns `SUBMITTED` only after the
journal write. This passed on Windows and WSL2 Python 3.11–3.13. It uses no
real Codex executable, provider account or external Nexus code.

The final full Python 3.13 suites passed at Windows 539 passed/73 skipped and
WSL2 598 passed/14 skipped, each with the expected injected legacy Pi warning.
The wheel remained SHA-256
`01b315cf82881f55eb7349511bbe5bedb7a88e41c7fe39b4de6e92672ac26ced`;
the updated sdist containing this test matched between Windows and WSL2 at
SHA-256 `a28decaf9eca334f171f9e05b4d13b48009808b01a2b58ffac9a1a89b446ec06`.
Strict Twine, clean-wheel consumer smokes, development release validation
(`publishable:false`) and offline wheel/sdist installation across all six
local Windows/WSL2 × Python 3.11–3.13 environments passed for this pair.
