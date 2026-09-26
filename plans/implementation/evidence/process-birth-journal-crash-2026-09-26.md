# Process birth journal crash cuts — 2026-09-26

The Core-owned `journal_crash_peer.py` now exits abruptly at three points
after an open's durable session claim and possible-effect admission:

| Cut | Reopened receipt | Reopened birth record |
|---|---|---|
| Before birth write | `SUBMISSION_STARTED` | Absent |
| Birth INSERT in uncommitted transaction | `SUBMISSION_STARTED` | Absent |
| After committed `record_process_birth` | `SUBMISSION_STARTED` | Present with exact identity |

Duplicate admission after reopen returns the original possible-effect
receipt in every case. No absent birth record is reconstructed from a PID.
The uncommitted cut directly injects a SQLite transaction in the test peer;
production writes use the Journal port.

`tests/test_journal_crash.py`: 11 passed on each local Windows and WSL2
Python 3.11, 3.12 and 3.13 environment.

An additional `test_process_birth_crash.py` cut runs a separate Core owner:
it durably claims/admits an open as possible-effect, launches a real
Core-contained child, reports its PID, and is killed before writing a birth
record. Windows process handles and Linux pidfds independently verify the
contained process stops after owner death. Reopening the journal finds the
original possible-effect receipt and no birth record; duplicate admission
returns that receipt without a fresh launch. It passed on the same six local
OS/Python combinations. Full Python 3.13 suites passed at Windows 544
passed/73 skipped and WSL2 603 passed/14 skipped, each with the expected
legacy Pi injected-failure warning.

Normalized Python 3.13 Windows/WSL2 builds were byte-identical: wheel
SHA-256 `63f12188eb648867c33445e5d504ee57db5a60c3d6209837078479d4a0ac0383`,
sdist SHA-256 `6b845ad362541e2c16d491d988cf3a81af2fda46fff709b9876416df24424599`.
The sdist includes the new test and crash peer fixture. Strict Twine and
development-mode release validation passed; `publishable` remains false.
Offline wheel/sdist installation and resource checks passed on local Windows
and WSL2 Python 3.13 for this exact artifact pair. The older artifact pair
has six-environment offline evidence; this new sdist was not rechecked offline
on Python 3.11/3.12.

The injected cut occurs after `spawn_owned_process` returns, not inside the
OS spawn or before containment has been established. It does not qualify
real providers, host restart/takeover, PID reuse under concurrent load, or
every kernel-space crash point. A birth record is historical diagnostic
evidence only and never authorizes PID control or takeover.
