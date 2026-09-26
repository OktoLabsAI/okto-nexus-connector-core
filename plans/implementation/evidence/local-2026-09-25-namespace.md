# Multi-Server namespace increment — 2026-09-25

Core local worktree; no commit yet. Windows 11 / Python 3.13.1.

The operation ledger now uses a composite `(server_id, executor_id,
operation_id)` key. In-memory sessions, inspection, reconciliation and
shutdown reports use `(server_id, executor_id, session_id)`. The existing
event cursor already used the full Server/executor/session/epoch identity.
Two-Server tests deliberately reuse the same operation and session IDs and
verify distinct native sessions, receipts, event payloads and shutdown keys.

Old development journal rows lacking Server/executor identity are preserved
but quarantined. A colliding operation ID raises
`LEGACY_OPERATION_UNSCOPED` before any native effect; it is not silently
migrated to a guessed Server or replayed. A later explicit migration/recovery
design is still required for deployments with old journals.

Commands (via `rtk`):

```text
pytest -q
python -m build --wheel --sdist
python tools/verify_wheel.py
```

Result: 135 passed, 66 skipped; one expected Pi fault-injection thread
warning. Clean-venv wheel import and contract hash verification passed; AST
scan found no direct application imports in the wheel.

Artifact SHA-256:

- wheel `c36caf589f87d5927d261260382d8b0e915c7922aea96fcb6c64a7ef462dc936`
- sdist `d40d7ddc76c0282b32717559ad288fc2c9c6f058ef719857e66620b15da0a123`

This proves local namespace separation for the tested API paths, not full
multi-Server quota, credential, profile, network or process isolation. Those
gates and real consumer integration remain open.
