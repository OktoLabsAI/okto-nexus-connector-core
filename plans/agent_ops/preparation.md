# Agent operations R3 preparation

User requested fetching main, bumping each impacted repository before
implementation, creating a versioned feature branch and committing/pushing each
milestone. `feature/v0.0.14` starts at fetched main
`19c99f15b17ae994653ad9e190964229a0e296e8` (0.0.13); the old branch is preserved.

This milestone changes package/public version metadata to 0.0.14. No NXL or
runtime contract changed. The candidate wheel was built locally and its 129
Python payload files compared byte-for-byte with source. Both consumers pin
0.0.14 and use the identical wheel (SHA-256
`5b9ffe72bef8c320e06fd9afee922f9c242960ca3cd3546daab5547ed157e8eb`).

Validation: `python -m pytest tests/test_public_docs.py -q`: 3 passed on Windows.
Consumer preparation checks: Nexus 10 passed; Connector 19 passed. This is not
a full regression or real-provider qualification. No packages were published.

Canonical scope, progress and evidence live in the Nexus repository:
`PLANO_CODEX_NEXUS_INTEGRACAO_ATENCAO_ONBOARDING.md`,
`plans/agent_ops/ledger.json`, and `plans/agent_ops/implementation-report.md`.
Next: finish BASE inventory; share pure contracts only when actually needed by
both hosts. This bump requires no data migration; reverting metadata alone does
not alter personal configuration or runtime state.
