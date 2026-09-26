# K04 bounded admission recovery — 2026-09-25

Before a fresh noncritical admission crosses the configured physical 80%
headroom gate, the SQLite reference journal now attempts one bounded recovery
pass under its local lock: compact at most 128 event bodies whose contiguous
durable-ingress ACK is already recorded, then request a non-waiting WAL
truncate checkpoint. It remeasures physical bytes inside the subsequent
admission transaction and still returns `JOURNAL_FULL` if pressure remains.
It never compacts unacknowledged bodies, invents an ACK, replays an effect or
uses the critical reserve to admit normal work.

Existing operation IDs are read before maintenance and checked again inside
the write transaction; duplicates remain readable under pressure while the
second check preserves cross-process fencing. Tests cover duplicate bypass,
ACKed-only compaction with an unacknowledged event retained, a pinned WAL
reader that keeps new work blocked, and admission after the reader releases
the WAL. The focused storage/compaction/page-full suite passed on Windows and
WSL2 (11 tests per platform). The full suites passed with 364 tests on Windows
and 419 on WSL2, with expected skips and the legacy Pi fault-injection warning.
The normalized wheel passes isolated installation checks on both OSes; two
Windows builds and one WSL2 build produced identical wheel/sdist SHA-256s as
recorded in `reproducible-build-2026-09-25.md`.

This is a single bounded attempt on *new admission*, not an independent
background maintenance service or a strict filesystem-size cap. A pinned
reader, busy writer or too much ineligible/uncompacted data can still prevent
recovery. The host must continue to monitor storage and enforce an external
physical quota for a hard bound.

2026-09-26 extension: both `record_event` (Core sequence allocation) and
`append_event` (explicit sequence) now attempt the same bounded ACK-only
recovery before a new noncritical event write nears physical headroom. An
existing explicit-sequence duplicate bypasses maintenance and is still
checked inside its write transaction. The event remains possible-effect if
maintenance itself hits `SQLITE_FULL`; no pre-effect retry claim is inferred.
Two targeted tests on Windows and WSL2 pinned the budget below the current
physical size, then verified ACKed-prefix compaction, survival of six
unacknowledged/new events and correct `EVENT_GAP` for a pruned cursor. This
does not yet automatically reclaim logical event quotas when physical usage
is low, and it does not impose a strict WAL filesystem cap.
The 22 focused storage/limit tests passed on Windows and WSL2 with Python
3.11, 3.12 and 3.13. The WSL2/3.12 virtual environment had an older wheel
installed, so its authoritative run set `PYTHONPATH=src` explicitly; the
initial stale-wheel run was not counted as a current-tree failure or pass.
Full Python 3.13 suites then passed on this revision: Windows 426 passed/73
skipped and WSL2 485 passed/14 skipped, each with the expected injected Pi
thread warning.

Further 2026-09-26 extension: a normal event that would cross any global,
Server/executor or session logical byte/row quota triggers one bounded
ACK-only compaction pass even when physical storage has headroom. Selection
prioritizes the affected session, then its Server/executor, before unrelated
streams; this avoids spending the 128-row pass on an older unrelated ACK
backlog. Both event-write APIs keep explicit duplicates out of maintenance.
Targeted Windows/WSL2 tests place 130 ACKed events in unrelated sessions,
then verify that an ACKed event in the saturated target session is reclaimed
first and its unACKed successor remains replayable. The same cases pass for
file-backed and in-memory journals. No ACKed data means no invented space;
this is still a bounded attempt, not an unbounded cleanup service.
Six further cases exercise byte and row pressure independently at global,
Server/executor and session scope. The 37 focused journal storage/limit/
compaction tests pass on Windows and WSL2 with Python 3.11, 3.12 and 3.13
(the WSL2/3.12 run explicitly imports `src`).
Full Python 3.13 suites passed on this revision: Windows 436 passed/73
skipped and WSL2 495 passed/14 skipped, with the expected legacy Pi injected
thread warning on each platform.
