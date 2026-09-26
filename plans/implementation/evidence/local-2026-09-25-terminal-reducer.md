# Terminal receipt reducer — 2026-09-25

Core local worktree; no commit yet. Windows 11 / Python 3.13.1.

Operation receipt transitions are serialized by a SQLite write transaction.
Duplicate receipts are idempotent, conflicting terminal outcomes fail, and
late weaker updates cannot downgrade a terminal receipt. A correlated native
terminal event and its receipt update now commit in the same transaction;
wrong-session terminal events roll back without spending a sequence/quota.
The async kernel returns the stronger receipt when a terminal event races the
synchronous adapter result. It still reports only `SUBMITTED` when no native
acceptance/completion evidence exists.

The private bridge associates a terminal native event with the active
`turn.submit` operation in that session. Pi's `agent_settled` is terminal only
after the prior message outcome is observed; Codex `turn/completed` and Claude
`result:*` use their copied protocol translators. Synthetic peer tests take
all three through the public async runtime and verify durable `SUCCEEDED`.
These tests do not qualify real provider versions or actual model tasks.

Commands (via `rtk`):

```text
pytest -q
python -m build --wheel --sdist
python tools/verify_wheel.py
```

Result: 154 passed, 66 skipped; one expected Pi fault-injection thread
warning. Clean-venv wheel import and contract hash verification passed; AST
scan found no direct Nexus application imports.

Artifact SHA-256:

- wheel `1faefe9fc472068971f48b01760363c8a72f995641b16f16154ece3c32839880`
- sdist `ba1f367487a099bf346ec9d3e75b4797ab078eeac4de30448599e45f2184ed0f`

Remaining: native operation correlation for queued/multiplexed edge cases,
approval/input flows, real provider/platform qualification, cancellation and
shutdown fault campaigns, and Server/Connector consumer conformance.
