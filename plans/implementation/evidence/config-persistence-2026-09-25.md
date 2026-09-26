# Local JSON configuration persistence — 2026-09-25

The trusted host can apply an already planned, explicitly selected JSON
configuration file through `apply_json_plan_file`. It serializes cooperating
writers with an adjacent OS lock, rereads and checks the exact source hash
under that lock, writes a unique backup before modifying an existing file,
then uses a fsynced temporary file and `os.replace`. It checks the source
again before replace to detect edits during apply. Removal uses
`plan_json_entry_removal` with exact host-supplied ownership proof, leaving
third-party entries and unrelated sections intact. Symlink targets and lock
paths are refused. No real harness configuration was modified in this work.

This is a cooperative filesystem transaction, **not** an unconditional
hardware/filesystem CAS: an editor ignoring the adjacent lock can still race
the final check and replace. On Windows, new files and backups inherit the
selected directory ACL; the trusted host must verify the ACL before applying
plans with sensitive content. `os.replace` is atomic for the target, but
Windows directory-entry crash durability is not claimed. A failure after
replace returns `OUTCOME_UNKNOWN` with `possible_effect=true`.

Verification on Windows/Python 3.13:

- Focused JSON plan/persistence tests: 15 passed. Coverage includes create,
  update, owner-proven removal, third-party preservation, stale hash, edit
  during apply, lock contention, idempotence, symlink refusal and simulated
  post-replace sync failure.
- Full `pytest -q`: 215 passed, 66 skipped.
- `python -m build --wheel --sdist` and `python tools/verify_wheel.py`:
  passed with clean wheel installation/import.
- Wheel SHA-256: `a397a8212b7e95726ffb83d8e19ff603bb26604c873fa97947608bed2b605d1b`.
- Sdist SHA-256: `6418532648355867048971a242db1414c18e58c4f40ba7f35560cb96fcb7a43d`.

TK-15 remains `NOT_RUN` as a full acceptance campaign; this work supplies
unit evidence only. Config selection/consent and platform ACL qualification
remain host integration gates.
