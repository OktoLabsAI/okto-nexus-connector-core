# Claude requesting-phase control evidence — 2026-09-25

The Core-owned Claude stream adapter no longer reports success when an
interrupt is dropped or an immediate steer is silently queued during the
unsafe requesting phase. Both operations raise `RuntimeCommandNotSent` before
any control or replacement-turn protocol write. The Core kernel treats that
specific proof differently from an ambiguous write failure: its SQLite
journal records `FAILED`, `possible_effect=false`, `retry_safe=true`, and
`CAPABILITY_UNSUPPORTED`. Deduplication returns that same failed receipt;
a new operation ID is required for a later attempt.

Verification on Windows/Python 3.13:

- Synthetic slow-start Claude peer: interrupt and steer rejected before write;
  original turn completes, no `control_response` or queued replacement.
- Legacy copied Claude suite: 29 passed, 7 skipped after adapting the two
  prior tests that expected the unsafe no-op/degradation.
- Public Core control test: rejected interrupt raises `CAPABILITY_UNSUPPORTED`
  and reconciliation exposes a durable safe `FAILED` receipt.
- Full `pytest -q`: 199 passed, 66 skipped.
- `python -m build --wheel --sdist` and `python tools/verify_wheel.py`: passed;
  clean wheel installation/import and local contract resources verified.
- Wheel SHA-256: `bf0a8f1e531ff73b137579b9e24753c6ae76d89d7ec50afd6ffdfa2e164861ae`.
- Sdist SHA-256: `92a42563a2c2cb2ce1c074670f12372c532c8f22b6bae8e0f60137ada415292a`.

No real Claude prompt was sent, no provider authentication was accessed, and
this does not qualify any native build or satisfy full K07 acceptance.
