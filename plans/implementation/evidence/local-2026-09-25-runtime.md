# Async runtime increment — 2026-09-25

Core local worktree; no commit yet. Windows 11 / Python 3.13.1.

Added the typed `RuntimeCore` protocol and `LocalRuntimeCore` implementation
for discovery, local preparation, open, submit, interrupt, events, inspect,
reconcile, close and basic shutdown. An injected native factory keeps host
authorization and provider secrets outside the Core. New tests exercise
idempotent open/submit, no native replay after restart, profile tampering,
agent fencing, durable event publication, event-pump failure, reconciliation,
and shutdown. One end-to-end test opens the copied Pi adapter against a
synthetic peer through the public async facade and verifies its persisted
turn events. `SUBMITTED` remains distinct from native acceptance/completion.

The private `CopiedAdapterSession` maps copied synchronous adapter commands,
native IDs and event payloads into the Core protocol. The real
`CopiedAdapterFactory` rejects every currently unqualified version before
secret resolution or process launch; its allowlist is intentionally empty
until Core-owned native/provider campaigns exist. This is structural
integration, not a claim that managed real providers are ready.

Commands (via `rtk`):

```text
pytest -q
python -m build --wheel --sdist
python tools/verify_wheel.py
```

Result at this step: 133 passed, 66 skipped; one expected Pi fault-injection
thread warning. Wheel/sdist build and clean-venv import passed. The wheel AST
scan found no imports of `okto_nexus` or `okto_nexus_connector`.

Artifact SHA-256:

- wheel `eee082ba98a4b39e663c15433f9844beb85fed2b5612ad2cedb87851018989b5`
- sdist `013a096c74e2eab4f6bd54d44e126548c3a0a23ec13f222069b5d7b22ee77305`

Remaining K04 work includes durable session/ownership ledger, lifecycle
timeouts and real drain/interrupt policy, bounded storage and critical-event
reservation, cross-Server namespace audit, real adapter qualification and
fault campaigns. K11 consumer integration remains not run.
