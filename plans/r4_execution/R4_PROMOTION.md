# Executable R4 contract — 2026-10-02

Core 0.2.53.dev0 promotes the separate R4 manifest to `executable` and exports
`R4_CONTRACT_REVISION` / `verify_r4_bundle`. The preview names remain compatible
aliases. `CONTRACT_REVISION` still denotes historical R3; its codec is unchanged.
Consumers must explicitly negotiate R4 and independently qualify native builds.

Pre-promotion evidence at Nexus commit `2d389db`:

- `plans/r4_execution/evidence/core052-promotion-conformance`: 151 installed
  Core contract/reducer tests, including historical R3 and rejection paths.
- `plans/r4_execution/evidence/vault-fixed-r4-campaign`: embedded five-action
  lifecycle passed; 14 remote lifecycle/recovery variants and four remote
  approval/input variants passed against the same Core .52 artifact and shared
  `_NativeFactory` synthetic peer. The overall campaign had three unrelated
  failures, retained as failures and subsequently corrected by directed tests.
- `plans/r4_execution/evidence/embedded-native-decisions`: eight installed
  local approval/input cases, approve/deny and HITL enabled/disabled. Operator
  authorization, exact native response, replay without repeated effects,
  sensitive-input nonpersistence and shutdown are asserted. Disabled execution
  refuses before native effect. This closes the local host coverage gap.

Post-promotion isolated installed conformance: **151 passed in 10.68 seconds**,
see `evidence/core053-promotion`. Wheel SHA-256:
`cc873031378793d374a9bbc00572c7a525f99c4246324a941713d866cc62c6b1`.
The 11 packaged historical v1 bundle files plus `protocol.py` and
`frame_codec.py` were compared byte-for-byte with the .52 wheel: all 13 match.
`contracts/generate_r4.py --check` passes; schema bytes are unchanged.

This promotes protocol executability only. It does not close host/provider,
independent-machine, UI, final artifact freeze or G0–G3 acceptance gates.
