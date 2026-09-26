# Core engineering closures: WAL bound, tree limit, real shutdown/resume, sustained saturation — 2026-09-26

## Hard WAL bound with automatic maintenance (K04)

`JournalLimits` gains `max_wal_bytes` (default 64 MiB) and
`reserved_wal_bytes` (default 4 MiB), validated like every other
quota/reserve pair. The pre-transaction maintenance pass now triggers on
WAL pressure alone (not only total-storage or logical pressure) and
attempts the bounded truncate checkpoint; the in-transaction admission
gate enforces the ceiling — normal writes up to
`max_wal_bytes - reserved_wal_bytes`, critical writes into the reserve and
up to the hard cap. A reader pinning the WAL therefore stops new
admissions with an honest typed `JOURNAL_FULL` instead of unbounded WAL
growth; releasing the reader lets the next write maintain itself with no
host intervention. Tests (`tests/test_journal_wal_bound.py`): quota
validation; pinned-reader stop and self-recovery; unpinned automatic
maintenance keeping the WAL bounded across ~900 writes; critical reserve
use and hard-cap stop.

## Owned-tree census and kernel-enforced per-tree process limit (K04)

`spawn_owned_process(..., max_tree_processes=N)`: on Windows the job
object applies `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` — process creation inside
the tree fails at the cap, kernel-enforced (test: a spawner that tries five
children under a limit of three creates at most two). On Linux the request
is recorded and reported as **not** kernel-enforced (test asserts all five
children spawn and `limit_enforced` is false — no silent enforcement
claim). `owned_tree_census(process)` is a bounded read-only PID census:
job-object members on Windows; on Linux the guardian plus the isolated
native session's process group (descendants escaping via `setsid` stay
outside both census and containment, unchanged). Unsupported backends
report `supported: false`. This is observability for hosts; admission-time
tree-count limits remain the installation slot ledger (eight owned trees
by default). Runtime-level per-launch wiring of the limit is future host
configuration.

## Real shutdown during active turns (K04/K05/K06/K07)

`tools/probe_managed_shutdown.py` opens each production-qualified adapter
through the full factory path, submits a long real turn, and calls
`runtime.shutdown(3, 3)` four seconds in:

- Codex 0.157.0: bounded 3.15 s, session outcome `unknown`, the interrupted
  turn's receipt honestly `CANCELLED` (terminal observed), late submit
  refused `RUNTIME_DRAINING`.
- Pi 0.87.1: bounded 3.06 s, outcome `graceful`, receipt `SUCCEEDED`
  (the drain interrupt settled the turn before close).
- Claude 2.1.282: bounded 3.89 s, outcome `unknown`, receipt `CANCELLED`.

## Real Codex cross-process resume (K05)

`tools/probe_codex_resume.py`: run 1 opened a thread, completed a real
turn and closed the app-server; the host located the persisted rollout
file for that exact thread under the user's `CODEX_HOME`; run 2 (a fresh
process) issued `thread/resume` with that thread ID, the adapter verified
the returned identity matched and the thread was idle, and one more real
turn completed. This qualifies the resume path for Codex 0.157.0 on
win32/x86_64 with the recorded fingerprint; the trusted-host grant seam
(`CodexResumeGrant` evidence checks) remains the production gate.

## Sustained saturation campaigns (K10/TK-40)

`tools/saturate_runtime.py`: four concurrent managed sessions over real
contained peer subprocesses on one runtime/journal, continuous submits
for 45 s with an urgent interrupt probe rotating every 7 s.

- Windows: 1,374 turns, 13,768 events, journal 6.4 MiB (bounded), zero
  stream faults, zero unexpected faults.
- WSL2: 1,826 turns, 18,288 events, journal 8.0 MiB (bounded), zero
  faults.

Urgent probes never blocked the load: every probe returned a typed
outcome (`STALE_TURN` pre-write refusal when no turn was live at that
instant, or a bounded adapter timeout — the synthetic peer only acks
aborts on its dedicated hold path). Admitted interrupts under saturation
remain covered by the held-turn fairness tests.

## External blockers recorded

- **Physical filesystem-full**: no root/admin available — WSL2 `sudo`
  requires a password, so no small tmpfs/loopback filesystem can be
  mounted. SQLite page-exhaustion evidence remains the honest stand-in
  (typed `JOURNAL_FULL`, no phantom facts, recovery when capacity
  returns); true ENOSPC stays unexercised.
- **Attach/Linux real substrate**: no native Linux harness installation
  exists on this host (Windows interop wrappers are rejected by design).

## Verification (all local, `rtk`-prefixed)

Full Python 3.13 suites passed Windows 622/74 and WSL2 680/16
(passed/skipped), each with the known injected legacy Pi warning; the new
focused suites (`test_journal_wal_bound.py`, `test_tree_census.py`) pass
on both OSes with their platform skips. Sustained campaigns ran on both
OSes with the results above.
