# TK-40 partial journal session fairness — 2026-09-26

The Core SQLite journal now tracks event bytes and rows by
`(server_id, executor_id, session_id)` in addition to its global and
Server/executor counters. Default per-session budgets are 16 MiB/50,000 rows,
with 1 MiB/1,000 rows reserved for critical categories. Normal admission is
refused at 80% of a session's configured budget; critical operation admission
and the finite critical event reserve remain available. Quota checks and
counter increments happen in the event write transaction, so two journal
connections cannot both spend the same remaining slot. Existing event bodies
rebuild the counter on upgrade, and durable-ingress-ACK compaction decrements
it without reusing stream sequence numbers. Zero-use session counters are
removed after compaction.

Operation admission also has a durable per-session row counter: 10,000 rows
by default, of which 100 are reserved for critical operations. A duplicate
operation remains queryable at saturation without consuming another slot.
The counter updates in the same write transaction as `operations_v2` and is
rebuilt from existing operation rows on upgrade. No receipt compaction exists,
so this cap is permanent for the lifetime of a session's retained journal.

Operation rows now also have a Server/executor counter and reserve (50,000
rows and 500 critical slots by default). Multiple sessions under one noisy
Server/executor cannot consume every global operation row, while another
Server/executor continues to admit. The counter is rebuilt from existing
operation rows on upgrade and updated within the same admission transaction;
two concurrent journal connections cannot both take the last slot.
The global operation-row count is now stored in a singleton transactional
counter as well, so normal admission does not scan all retained operation
rows at scale. Upgrade reconstructs it from existing rows. Tests cover the
global normal/critical split, duplicate admission at saturation, migration
from a pre-counter journal and two competing SQLite connections.
The 34 focused storage/limit tests passed on Windows and WSL2 with Python
3.11, 3.12 and 3.13 (WSL2/3.12 explicitly imports `src`). Full Python 3.13
suites passed on this revision: Windows 440 passed/73 skipped; WSL2 499
passed/14 skipped, each with the expected injected legacy Pi thread warning.

`tests/test_journal_limits.py` exercises a noisy session reaching its row and
byte limits while another session under the same Server/executor continues to
record events and admit work. It checks critical reserve, 80% admission,
ACK/compaction recovery, upgrade reconstruction and concurrent saturation
through two SQLite connections. Additional tests exercise normal/critical
per-session operation slots, duplicate admission, restart retention,
reconstruction from old operation rows and concurrent admission through two
connections. Targeted tests passed on Windows and WSL2.
Further tests cover Server/executor normal/critical slots, another Server's
progress, duplicate admission, upgrade reconstruction and concurrent writers.
The updated full Python 3.13 suites passed: Windows 424 passed/73 skipped;
WSL2 483 passed/14 skipped, with one deliberately injected legacy Pi thread
warning each. The focused quota/storage set passed 20 tests on both systems.

The optional runtime event sink now replays from the journal on a separate
per-session task. There is no per-event in-memory sink queue; a stalled sink
cannot block native pipe reads after append. A callback failure leaves its
cursor unadvanced and the next append retries from durable storage. Synthetic
runtime tests hold the sink for 25 native events, verify all 25 became durable
before release, execute an interrupt during the stall, then verify ordered
delivery; a second test checks retry after a sink exception.
The full Python 3.13 suites passed after this change: Windows 422 passed,
73 skipped; WSL2 481 passed, 14 skipped. Each retains one expected legacy Pi
injected-thread warning. The final interrupt assertion was also rerun in the
targeted Windows test.

A later race audit found that a sink callback could fail after another native
event had been appended but before the existing delivery task exited. The
pending wake now causes exactly one fresh journal replay attempt; with no new
append, a broken sink stops instead of spinning. A durable pump-fault event
also notifies the optional sink. Deterministic targeted tests cover both the
in-flight-append failure and the post-failure append, plus pump-fault
notification; all four sink tests pass on Windows and WSL2 Python 3.13.
The four focused sink tests also pass on both systems with Python 3.11 and
3.12 (WSL2/3.12 explicitly imports `src`). Full Python 3.13 suites for this
revision passed: Windows 438 passed/73 skipped, WSL2 497 passed/14 skipped;
each retains the expected injected legacy Pi thread warning.

This is not the whole TK-40 gate. Global and Server/executor reserves remain
finite, so enough critical traffic can still exhaust the journal. Native
pipe fanout with real providers, sustained slow-consumer/journal saturation,
physical WAL quota and real multi-host fairness/performance campaigns remain
open. A journal refusal after a provider effect is reported as
possible-effect uncertainty, not safe retry.
