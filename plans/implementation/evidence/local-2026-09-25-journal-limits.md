# Journal quota increment — 2026-09-25

Core local worktree; no commit yet. Windows 11 / Python 3.13.1.

The SQLite journal maintains transactional payload-byte and event-row counts
globally and by Server/executor. Default global budget is 256 MiB of event
bodies with 16 MiB reserved for critical categories. Noncritical events cannot
consume the reserve. At 80% of global or Server budget, new noncritical
operation admissions return `JOURNAL_FULL`; interrupt/close admissions retain
reserved operation rows. Exact event duplicates remain idempotent even at
capacity. Counter seed on opening a pre-quota journal conservatively counts
all existing events. Tests cover byte and row ceilings, two Server namespaces,
two concurrent journal connections, restart persistence, conflict rollback,
critical reserve and work-admission threshold. Replay and contiguous-watermark
queries now read at most 128 rows per SQLite page; the async facade no longer
materializes the whole replay stream. A 300-event fixture crosses page bounds.

SQLite `SQLITE_FULL` is mapped to `JOURNAL_FULL` at write sites, with
`possible_effect`/`retry_safe` reflecting whether native work may already
have occurred. An actual disk-full fault injection was not run; this mapping
is code-level evidence only.

Commands (via `rtk`):

```text
pytest -q
python -m build --wheel --sdist
python tools/verify_wheel.py
```

Result: 144 passed, 66 skipped; one expected Pi fault-injection thread
warning. Wheel and sdist built. Clean-venv install/import and contract hash
verification passed; wheel AST scan found no direct Nexus application imports.

Artifact SHA-256:

- wheel `1cf001884ba0afecb2cfa52ad8ad1d226d8244c2144d27a819a89ac3604d82b9`
- sdist `976dc1041cc118125b98f07ed7482b87481e21a0e9685d4862d1185a2e4fc8dd`

These limits count serialized event bodies, not SQLite B-tree, indexes, WAL,
operations or filesystem overhead; they do not yet prove the plan's total
256 MiB on-disk ceiling. Compaction, per-binding fairness, disk-full fault
injection and critical terminal delivery under
saturation remain open K04/K10 gates.
