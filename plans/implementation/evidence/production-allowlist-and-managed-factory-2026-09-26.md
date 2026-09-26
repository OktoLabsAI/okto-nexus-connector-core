# Production allowlist and managed-factory smoke — 2026-09-26

User decision (option a): the three real builds observed by the authorized
2026-09-26 campaigns are now production-qualified in
`native/adapters/compatibility.py`. The grants are exact tuples of native
kind, observed version, host platform, parsed architecture and selected file
fingerprint:

- `codex` 0.157.0, win32/x86_64, `sha256:ed1c7b36…b1f`
- `pi` 0.87.1, win32/x86_64, composite Node+CLI fingerprint
  `sha256:3765c5c5…058` (binds the trusted Node executable and the installed
  CLI JavaScript — paths and hashes; any other pair or changed byte does not
  inherit the grant)
- `claude_code` 2.1.282, win32/x86_64, `sha256:fc0e3af0…484`

Both the conversation and the control qualification sets carry exactly
these keys. `control_observation` is now kind-aware: Claude advertises
`interrupt` only (it has no steer vocabulary and public `turn.steer` is
refused for `claude_stream`), while Codex and Pi advertise
`["steer", "interrupt"]`. A focused test proves any drift — version,
platform, architecture or file bytes — loses the grant entirely, and that
the control lists match the recorded campaigns. This is a wire-contract
qualification for managed conversation plus the listed controls: it is not
resume/deduplication, not the Pi work bridge, not native approval traffic,
and not a promise that every model task succeeds. Attach stays unqualified.

`tools/probe_managed_factory.py` then exercised the full production path per
adapter — explicit discovery selection, sealed version probe, profile
preparation, `CopiedAdapterFactory` (now passing the allowlist gate),
`LocalRuntimeCore.open`, one tiny authorized model turn, journal terminal
correlation and bounded shutdown:

- Codex 0.157.0: open/submit `SUBMITTED`, terminal `turn/completed`
  correlated to the submit with outcome `success`, receipt `SUCCEEDED`,
  honest `OUTCOME_UNKNOWN` close, contained shutdown.
- Pi 0.87.1: same shape with `agent_settled` terminal, receipt `SUCCEEDED`,
  close `SUBMITTED`.
- Claude 2.1.282: `result:success` terminal (prefix-matched — the subtype
  is part of the native type), receipt `SUCCEEDED`, honest unknown close.

The Claude managed template now mirrors the copied connector's qualified
default argv (`--verbose --include-partial-messages`, load-bearing for
interrupt safety). The discovery probe env filter applies to the caller's
overlay, so trusted hosts must supply the essential variables (PATH,
SYSTEMROOT, …) in the overlay — Node without SYSTEMROOT fails to start and
the version observation correctly returns `version_not_observed` instead of
guessing.

Scope limits: Windows/x86_64 only, one build per adapter, no HITL traffic
yet, no resume, no Linux/macOS, no sustained load. Remote (Connector-side)
use of the same adapter remains future work.
