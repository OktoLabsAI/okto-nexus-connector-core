# Conditional control evidence — 2026-09-25

`ControlOperation.expected_turn_id` now survives the public Core, private
async native port, bridge, and `HarnessCommand`. The bridge rejects idle
control or a non-matching observed native turn before adapter invocation.
The copied Codex adapter independently checks a stale expected ID before
writing `turn/interrupt` or `turn/steer`. Such guaranteed-unsent failures
become durable `FAILED` receipts with `STALE_TURN`, `possible_effect=false`,
and `retry_safe=true`; ambiguous native failures still use `OUTCOME_UNKNOWN`.

Public `turn.steer` requires action authorization, nonempty bounded content,
and an explicit expected native turn ID. It is currently admitted only for
`codex_app_server`, whose private adapter uses the native `turn/steer` method.
Claude interrupt+reprompt and Pi steer are not exposed as equivalent public
operations. No native build has been qualified by these synthetic tests.

Verification on Windows/Python 3.13:

- Bridge tests prove idle/stale rejection without native adapter invocation
  and matching-ID forwarding.
- Copied Codex peer tests prove stale steer/interrupt produce no control
  request in the peer log.
- Public RuntimeCore tests prove action/adapter gating and ID forwarding.
- Kernel tests cover both safe `CAPABILITY_UNSUPPORTED` and `STALE_TURN`
  journal outcomes.
- Full `pytest -q`: 205 passed, 66 skipped.
- `python -m build --wheel --sdist` and `python tools/verify_wheel.py`:
  passed, including clean wheel installation/import.
- Wheel SHA-256: `2209bd0ade98af45d5bcc8f24be6fd29b76e506aeb41034521cc1c62b2e0d8ec`.
- Sdist SHA-256: `bf898de2c49a7105ad0751cad01e17f545859d3acc87df1f2ea07f9cf6c46b8c`.

Provider-real control and multi-host acceptance tests remain `NOT_RUN`.
