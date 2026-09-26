# SQLite physical pressure guard — 2026-09-25

K04 partial evidence on Windows/Python 3.13. `JournalLimits` now has an
overall observed-storage budget and critical reserve. The Core reports main
database, WAL and SHM bytes plus SQLite page/free-page counts. Admission of
new work and noncritical events fails closed with `JOURNAL_FULL` when measured
storage plus conservative page headroom approaches the configured threshold;
critical writes retain separate headroom. The journal configures SQLite's
`max_page_count`, `journal_size_limit` and a 256-page passive auto-checkpoint.
An explicit non-waiting `checkpoint_wal` reports busy/log/checkpointed counts.
The runtime facade exposes these operations without database-table access.
The main file's path identity is checked before storage accounting, so a
replaced path cannot silently report a different file's size.

Tests exercised physical pressure, a pinned WAL reader, checkpoint recovery,
and a path-identity mismatch. Verification:

- `pytest -q tests/test_journal_storage.py tests/test_journal_compaction.py
  tests/test_journal_limits.py`: 16 passed.
- `pytest -q`: 191 passed, 66 skipped.
- `python -m build --wheel --sdist`: passed.
- `python tools/verify_wheel.py`: clean installation/import, bundle hashes and
  no Nexus/Connector imports in packaged Python passed.

SHA-256: wheel
`8068ca0001ac2d6458afb1c1a54ca1a034a4afbbc8c1fe508605751a9b24a929`;
sdist `90b9aa51c772d7f7b26034a44236a2bb639c9b614e629bb43b74d9c761ba92bc`.

This is an observed-pressure gate, **not a strict physical-size guarantee**.
SQLite documents that an active reader can prevent WAL reset/checkpoint; the
WAL can grow despite a main-file page limit, and `journal_size_limit` applies
after reset/checkpoint. A per-installation OS/filesystem quota or similarly
qualified containment, background maintenance beyond fresh-admission recovery, filesystem-full
fault injection and multi-process production load remain open. A later bounded
eligible-only recovery attempt on fresh admission is documented in
`journal-admission-recovery-2026-09-25.md`; background maintenance remains
open. K04 and its
full TK/J gates are not complete.
