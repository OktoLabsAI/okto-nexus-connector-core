# M5a — Shared startup refusal foundation

Status: Core contract qualified; consumer integration incomplete. 2026-10-17.

The current host can persist a scoped `startup_failure` association for a
`runtime.open` that failed before native admission. The journal atomically
records `FAILED / PREPARATION_FAILED`, with no possible effect and safe retry,
or preserves a conflicting original native intent. A delayed original producer
cannot admit that operation ID after the refusal wins. This does not fabricate
a lease denial, session claim, process exit, capacity release or server closure.
The host must still quiesce the producer and separately prove resource release.

The association carries exact admission provenance and uses a dedicated hash
domain. The shared operation-refusal validator/persister accepts it.
Connector startup recovery does not consume it yet: its reproduction still
shows a preparation exception closing the whole control connection.

Qualification: 107 selected source cases and 149 installed cases passed on
Windows. The latter verified 161 installed package files against the built
wheel, ran with an isolated interpreter, and covered refusal replay, original
intent races, four commit/reply cuts, existing native stages, corrupt scopes,
and unchanged physical reservations. See `runtime-lifecycle-m5a-results.json`.
Wheel SHA-256:
`dfdfef2edeb9f8db8697e6b850c05a704698e692a3592ed6d9d827887235f816`.

These checks also found an existing preopen contract manifest referencing the
base schema hash from before inventory format 3. The installed previous wheel
raised `CONTRACT_BUNDLE_INVALID`. Updated the manifest to the current base hash
and added a regression comparing the two augmented reconciliation branches with
the base after removing exactly their extension. No reconciliation authority
was weakened. This defect is not established as the cause of the reported
production-wide Recovering state.

Connector's 52 selected installed preopen/launch/execution cases passed with
this Core. Nexus consumer qualification has four failing remote publication
cases under investigation; no joint rollout or M5 completion is claimed.
The full milestone still requires host integration, differential recovery,
lost acknowledgments, resource containment and caller-outcome validation.
