# M3e — Durable refusal after a local session fence

2026-10-16. Core 0.0.12 / feature/v0.0.12.

Added a strict internal stopped-session association for productive work not yet
admitted by Core. The trusted host supplies the exact retained session/channel
scope and a latched LEASE_EXPIRED or LEASE_REVALIDATION_REQUIRED failure. It is
not a fabricated server lease denial or proof of native process termination.
Containment remains a separate obligation. Control actions cannot use this path.

The common journal CAS records FAILED, possible_effect=false, retry_safe=true.
It never overwrites a different/native intent, including a durable admission
whose external effect is still unknown. Associations contain no command payload
or credentials and use normal journal capacity, preserving control reserves.

Validation: 43 source cases and **43 installed cases passed** (no skips/errors).
Coverage includes strict scope, supported errors/actions, immutable intent,
existing effects, persistence cuts, idempotent replay and capacity failures.
The first source collection loaded the old global Core; rerunning with explicit
source pythonpath fixed the test invocation. Installed qualification used -I
and compared all 156 package files with the wheel.

Wheel SHA256: `d658de647db7e9dec106ce496525703d9284492ded401cb3ad55c901e460e8cf`.
Evidence: `build/runtime-lifecycle-m3e-installed/manifest.json`, `results.xml`.

The scope is already-opened remote sessions. Initial preparation/opening without
an opening fact still uses conservative host reconciliation. Transport failures
and uncorrelated authority failures retain global handling. This checkpoint does
not complete M3/M5 and is not a live global rollout. The running Nexus remains
on the M3c installation qualified through the UI.
