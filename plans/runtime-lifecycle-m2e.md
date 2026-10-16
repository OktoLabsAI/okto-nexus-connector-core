# M2e — Authenticated never-started release

2026-10-16. Core 0.0.12, feature/v0.0.12. Consumer integration is recorded in
the Nexus canonical runtime lifecycle ledger; this is not completion of M2.

The negotiated `nexus-launch-recovery-v1` extension distinguishes `NOT_STARTED`
from `EXITED`. It transports the original fenced producer identity and the
`NEVER_CLAIMED` proof, bound by digest to the opening's wire intent. It requires
a strictly newer connection generation, the same original session/operation and
owner, a FAILED opening without a native identity, and no live resource slots
or process-birth record. It does not change `possible_effect`, `retry_safe`,
historical receipt bytes, or permission to replay work.

The codec composes a named schema overlay with the base R4 contract and optional
preopening refusal extension. The proof schema is hash-verified and packaged in
the wheel. Existing R4 schema and manifest bytes remain unchanged because they
also validate durable historical records, not to retain old-peer interoperability.

Installed Windows campaign: **95 passed**. Covered independent proof projection,
scope/generation contradictions, invalid proofs, codec negotiation, base bundle
integrity, preopening composition, receipt/resource regressions, durable launch
settlement and five disposable Windows owner-crash boundaries.

- Wheel: `build/process-launch-m2e-dist/okto_nexus_connector_core-0.0.12-py3-none-any.whl`
- SHA256: `5ab1f03165c5dcdb7e879a6c773f766a8a6b5cd479c529588f833d47096d13c8`
- Results: `build/process-launch-m2e-installed/results.xml`
- Results SHA256: `526a715a8ba34f38d01cd9688ac1d23da4345cb2761de687c6887df0cb19ba97`
- Manifest SHA256: `27019b479e8c2c7ad1cf7d59b32aa93835fcefd42265bab4f3eedd62c249c801`
- Runner: `tools/run_r4_installed.py`, isolated interpreter, temporary working
  directory, byte comparison of every installed Core package file against wheel.

Selected tests: `test_launch_release_r4.py`, `test_r4_resource_release.py`,
`test_r4_receipt_bridge.py`, `test_r4_development_bundle.py`,
`test_r4_preopen_bundle.py`, `test_process_launch_settlement.py`,
`test_planned_process_launch.py`.

Limits: this does not qualify real provider behavior, Linux/macOS containment,
or another physical host. Native containment uses the shared controller from M2c.
