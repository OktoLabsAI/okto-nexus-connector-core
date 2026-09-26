# Journal/event increment — 2026-09-25

Core local worktree; no commit yet. This increment is wholly Core-owned and
does not import the sibling Nexus checkout. Windows 11 / Python 3.13.1.

The event API now requires a fully scoped cursor (Server, executor, session,
epoch); an unscoped session ID cannot read another Server's event stream.
`record_event` allocates sequence and inserts body in one SQLite write
transaction. Tests cover restart persistence and two simultaneous journal
connections. The native event ingestion seam maps extracted adapter events
into Core events, rejects wrong sessions/oversize payloads, and publishes only
after durable commit. A failed publisher leaves the record available for
replay. It does not yet run a continuous adapter event pump.

Commands (via `rtk`):

```text
pytest -q
python -m build --wheel --sdist
python tools/verify_wheel.py
```

Result: 127 passed, 66 skipped; one intended Pi reader fault-injection
thread warning. Build and clean-venv wheel import passed. Wheel AST scan found
no imports of `okto_nexus` or `okto_nexus_connector`. The build was performed
before two test-only assertions were added; no package source changed between
that build and final suite.

Built artifact SHA-256:

- wheel `0c5c092822d0d7d113b32da1c5320c2101d62c975942e51e845aefbd2490627a`
- sdist `8214307d1bb42cb4f449d0ea29c9c8b3e09fee6c56ad6176e458d02a3855f512`

This is a K04 increment, not full K04 qualification. Bounded journal storage,
critical-event reservation, live pump/backpressure, Linux containment,
runtime lease/reconcile/shutdown and multi-host fault scenarios remain
`NOT_RUN` or unimplemented.
