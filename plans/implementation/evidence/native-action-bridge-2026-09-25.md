# Typed non-MCP native-action port — 2026-09-25

The Core now contains a private, typed `ScopedNativeActionBridge` for
`handoff.get`, `handoff.claim` and `handoff.complete`. It accepts only matching
`native-cap:` grants and host `ExecutionContext` scope, exact connection and
authorization/configuration revisions, live monotonic lease and intersected
action sets. Requests carry session, handoff and operation identities;
claim has a stable idempotency key and completion requires a positive claim
epoch. A bounded JSON result is forwarded only to an injected canonical
backend. Generic MCP envelopes/catalogs and arbitrary action strings are not
accepted. This module does not contain an inbox, claim engine, approval
authority, MCP server or HTTP transport.

Backend exceptions on mutating claim/complete are reported as
`OUTCOME_UNKNOWN` with possible effect, not as safe retry. Context-read
exceptions are reported as safely retryable. Backend errors that already
carry a Core code pass through. The host's canonical use cases remain the
authority for eligibility, claim CAS, deduplication, completion and result.

Verification on Windows/Python 3.13:

- Focused tests: 6 passed, including matching scope, stale revision/lease,
  wrong capability, MCP-shaped input, oversized result, backend lost reply
  and safe read failure.
- Full `pytest -q`: 241 passed, 66 skipped.
- `python -m build --wheel --sdist` and `python tools/verify_wheel.py`:
  passed with clean wheel import of the new port.
- Wheel SHA-256: `5e6c010fcfee264ef1f8e0c737354f32c19612c8a3c8dd6869ed87c90cb53f1a`.
- Sdist SHA-256: `15128a1b89b4ca6a1ab4094586c526cb9beada3754989d13b637ce6237eb6cb1`.

TK-33 and J17 remain `NOT_RUN`: the Pi extension, two real host backends and
canonical application integration do not yet exist in this Core worktree.
