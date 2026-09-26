# K04/TK-17 read-only process-birth observation - 2026-09-26

The durable owned-container birth record can now be compared to a current
read-only OS observation through `RuntimeCore.observe_process_birth`. The
result is `UNRECORDED`, `MATCHING_LIVE`, `DIFFERENT_BIRTH`, `NOT_RUNNING`,
`NOT_OBSERVED`, or `UNKNOWN`. Linux reads boot ID and the guardian's
`/proc/<pid>/stat` start tick/state. Windows opens the PID with only
`PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE`, compares creation FILETIME
and performs a zero-time wait. No process is signaled, lease renewed, slot
freed, or ownership state changed by this method.

Real Core-owned child tests on Windows and WSL2 observed a matching live
birth, detected a deliberately altered token as a different birth, and
reported the stopped child as not running/not observed. A foreign-platform
record remains unknown. The integrated synthetic copied-adapter factory test
also proved that the public runtime observes the same birth it persisted.
The first Windows focused run exposed a missing `SYNCHRONIZE` access right:
the method conservatively returned `UNKNOWN`, not a false match. After the
read-only access correction, focused tests passed on Windows and WSL2 Python
3.11–3.13 (78 each).

Full Python 3.13 suites passed: Windows 540 passed/73 skipped and WSL2
599 passed/14 skipped, each with the expected deliberately injected legacy
Pi thread warning. Normalized Windows/WSL2 builds matched byte-for-byte:
wheel SHA-256
`63f12188eb648867c33445e5d504ee57db5a60c3d6209837078479d4a0ac0383`,
sdist SHA-256
`d7ffbedf56a1fb13bd03379c733b3a33f8657a8f95d2c157a603a92c1a703cd9`.
Strict Twine, clean-wheel embedded/remote consumer smokes, development
release validation (`publishable:false`) and offline wheel/sdist installation
in all six local Windows/WSL2 × Python 3.11–3.13 environments passed.

`MATCHING_LIVE` is an instant observation only: the process may exit next,
and neither it nor a birth record proves tree ownership, lease continuity,
or a safe reattach/kill after restart. Provider, real host adapter, and
broader platform qualification remain open.
