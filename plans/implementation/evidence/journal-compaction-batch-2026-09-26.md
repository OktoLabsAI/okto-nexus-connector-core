# K04/K10 bounded journal compaction batch - 2026-09-26

`SQLiteJournal.compact_acked(max_rows=...)` fetched a caller-sized set of
ACKed rows into memory. It accepted `True` as one row, passed a fractional
batch to SQLite, and passed an out-of-range integer far enough to raise an
untyped `OverflowError` during the write transaction. The public
`LocalRuntimeCore.compact_events` facade delegated the same value to any
injected host journal without a boundary check.

The Core now requires an exact integer from 1 through 4,096 at both the
facade and SQLite implementation. Invalid batches fail with `ValueError`
before any deletion or host-journal call; the default remains 128. The
reproducing test demonstrated the previous failures and verifies the ACKed
event remains replayable after every invalid request. A separate injected
host-journal spy proves rejection before delegation. A valid upper-bound
batch is accepted. This bounds the Python row-list size for an explicit
compaction call; it does not bound SQLite WAL growth or filesystem usage
under a pinned reader.

The focused compaction suite passed on Windows and WSL2 with Python
3.11-3.13 (15 tests in each environment). The full Python 3.13 suites
passed: Windows 493 passed/73 skipped and WSL2 552 passed/14 skipped,
with the expected injected legacy Pi thread warning.

Normalized Windows/WSL2 builds matched byte-for-byte: wheel SHA-256
`6a40a33ee9b2664c609066c80fadc5529da4d5eaf8c34e50589c11b5eeb7f514`,
sdist SHA-256
`e996306abd7da5078e8ce8c2691592638e98e13385a9287d545396efa5896f5d`.
Strict Twine, clean-wheel embedded/remote consumer checks, Windows offline
wheel/sdist installation, and development-mode release validation passed;
`publishable` remains false.
