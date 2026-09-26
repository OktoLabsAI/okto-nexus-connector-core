# K10.3 partial hostile-configuration validation — 2026-09-26

`JournalLimits` now rejects non-integral values, booleans and integers above
SQLite's signed 64-bit range for every byte/row budget before opening a
journal. `SQLiteJournal` also rejects a non-`JournalLimits` limits object
before creating a database file. Lease timing in `LocalRuntimeCore` rejects
non-finite, boolean and untyped values at construction. `shutdown` rejects
the same malformed timing and untyped policies with `VALIDATION_ERROR`
before changing runtime drain state.

Targeted tests iterate every journal limit through hostile values and test
both runtime timing paths. All three targeted tests pass on Windows and WSL2
with Python 3.11, 3.12 and 3.13 (WSL2/3.12 explicitly imports `src`).
Full Python 3.13 suites passed on this revision: Windows 443 passed/73
skipped; WSL2 502 passed/14 skipped. Each retains the expected injected
legacy Pi thread warning. The updated local wheel/sdist passed strict Twine,
clean-wheel consumer verification, Windows offline installation and
development-mode release validation (`publishable: false`).

This is not the full TK-39/K10.3 fuzz gate: parser/Unicode/config mutation
campaigns, provider output and real host boundary tests remain unexecuted.
