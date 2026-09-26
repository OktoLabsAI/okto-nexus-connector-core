# Monotonic lease increment — 2026-09-25

Core local worktree; no commit yet. Windows 11 / Python 3.13.1.

`LocalRuntimeCore` now uses an injected monotonic clock for admission and a
per-owned-session lease watcher. The default lease window is capped at 120 s;
expiry blocks new work and closes owned native resources after 15 s grace.
`renew_lease` performs a connection-generation CAS, rejects changed session
ownership generation, and only extends a live session under the same identity.
`revoke_lease` fences new admissions permanently for that session. Tests with
an injected clock cover renewal during grace, stale-channel rejection,
revocation, close after grace, and an overlong lease. The automatic close has
a deterministic, reserved internal operation ID and a durable possible-effect
record before the native close call when the journal is writable.

Close/shutdown report ownership released only when the native backend observes
the process stopped. An unobserved close leaves `OUTCOME_UNKNOWN` and ownership
`owned` for reconciliation. Actual crash/reboot recovery, persisted lease and
process birth records, disk-full behavior during internal close, and real OS
termination deadlines are not yet qualified.

Commands (via `rtk`):

```text
pytest -q
python -m build --wheel --sdist
python tools/verify_wheel.py
```

Result: 159 passed, 66 skipped; one expected Pi fault-injection thread
warning. Clean-venv wheel import and contract hash verification passed; wheel
AST scan found no direct Nexus application imports.

Artifact SHA-256:

- wheel `22e7155469c621121834e3949cb0bfa019626c7a092e6ca95b671467b5b205ae`
- sdist `77c5ce94372f691f688c79ff16f30c98722d258731f6f784dba9dba8a3635a8f`

This is local process-lifetime evidence, not a full K04 reconnect/lease or
TK/J end-to-end qualification.
