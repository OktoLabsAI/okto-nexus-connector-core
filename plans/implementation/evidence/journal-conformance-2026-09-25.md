# K04.1/K10.5 reusable Journal-port conformance — 2026-09-25

`nexus_connector_core.testing.run_journal_conformance` runs one
application-neutral scenario against an injected `Journal` port and returns
an immutable normalized trace. It checks scoped admission and exact
ID/hash/session deduplication, intent conflict, possible-effect marker,
`OUTCOME_UNKNOWN` without retry, later terminal resolution, adapter proof of
no write, atomic terminal-event receipt, out-of-order event gap, duplicate
hash conflict, contiguous ACK, replay and compaction gap. It uses no native
process, network service, application repository or second backlog.

The scenario exposed a real reference-journal gap: duplicate admission
checked `operation_id` and `intent_hash` but not `session_id`. The Core now
rejects a session mismatch with `OPERATION_CONFLICT` before returning a
deduplicated receipt. The same conformance kit passes on the Core SQLite
journal and deliberately fails for a test adapter that ignores that conflict.
The clean-wheel verifier executes the kit in a fresh installed environment.

This is a reusable host-port test, not evidence that the actual Nexus Server
embedded journal adapter conforms. That adapter must run this same kit,
including restart/fault scenarios still to be added, and its normalized trace
must be compared with the reference. No Server or Connector repository was
modified in this step.

Local development artifact SHA-256 values: wheel
`e8a5d1267f1328f05f6a845263189e7b67b2744773ac5c6d520c8a4994dc7bc0`;
sdist `86e4094fe147cd5c0842490d984e7168f09a42295556a8af498d199983832a15`.

## Follow-up: durable session claim

The kit now exercises `claim_session=True` on an open admission: an exact
duplicate returns the old receipt, while a different operation in the same
Server/executor/session namespace must raise `SESSION_CONFLICT`. A deliberately
faulty host adapter that drops the flag fails the kit. This passed on the
Core SQLite reference journal on Windows and WSL2 Python 3.11-3.13; real
Server adapter parity remains untested. See
`plans/implementation/evidence/session-claim-fence-2026-09-26.md`.
