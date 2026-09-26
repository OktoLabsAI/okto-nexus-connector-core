# K04/K10 SQLite page exhaustion — 2026-09-25

The reference journal now checks `Connection.in_transaction` before rollback.
SQLite may automatically roll back after `SQLITE_FULL`; an unconditional second
`ROLLBACK` previously raised `OperationalError` and hid the typed `JOURNAL_FULL`
error and its effect/retry attribution.

`tests/test_journal_disk_full.py` reduces `PRAGMA max_page_count` to the
current page count of a temporary on-disk SQLite journal. A large native event
then fails with `JOURNAL_FULL` and `possible_effect=True`, without a stored
event or consumed stream sequence. A large new admission fails with
`JOURNAL_FULL`, `retry_safe=True` and no receipt. After raising the page limit,
the event persists at sequence 1 and the same admission key can be inserted.
Both focused tests pass on Windows/Python 3.13 and WSL2/Python 3.12. The full
local suites pass: 363 tests on Windows and 418 on WSL2, with expected skips
and one legacy Pi fault-injection thread warning per platform. The clean-wheel
installation check passes, and two Windows builds plus one WSL2 build produce
identical wheel/sdist hashes as recorded in `reproducible-build-2026-09-25.md`.

This exercises real SQLite page exhaustion, not an actual full filesystem or
WAL pressure from a pinned reader. Automatic compaction/checkpoint recovery,
hard physical quota and broader K10 saturation/fairness remain pending.
