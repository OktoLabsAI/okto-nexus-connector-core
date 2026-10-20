# M2b — Atomic admission and shared producer control

2026-10-16. M2 remains in progress; native factory/host integration is next.

The journal can now persist the launch identity in the same transaction as its
session claim, opening generations and operation. A crash before the effect
marker leaves a recoverable PREPARED intent. Insert/update failure rolls back
the entire admission, including usage counters. Duplicate operations return
their original receipt and keep the original launch identity.

The kernel carries this identity through admission before marking any possible
effect. Claiming a producer requires that marker in the same storage transaction
as the claim CAS. An intent alone grants no launch permission.

`ProcessLaunchController` shares launch/recovery policy over storage and
exclusion ports. It reads durable state after acquiring the per-producer OS
gate, checks current authority before and after durable I/O, and claims once.
Recovery fences the producer before container observation. A never-claimed
producer can be proven stopped without a container; a claimed one needs explicit
container stop proof. Busy/unknown work retains its resources. The controller
does not release slots or manufacture operation results.

Cancellation of an async waiter does not end its underlying thread. Runtime
integration must retain/supervise the producer task as it already does for
native opening. A busy producer does not prevent a sibling from progressing.

Installed-wheel validation: **80 passed**, zero failures/skips, Windows 11
AMD64/Python 3.13.1. Covers M2a contracts plus atomic admission rollback/reopen,
effect ordering/deduplication, fencing before delayed startup, cancellation
while a worker holds its OS gate, independent sibling progress, uncertainty
without container proof, and authority lost during storage. `pip check` passed.

- Wheel SHA256: `c8567bd036faef028a90ef79dfbb3f6e86f20171ec2c533a97720cff2f36d69a`
- Local evidence: `build/process-launch-m2b-installed/manifest.json`,
  `build/process-launch-m2b-installed/results.xml`.
- Result SHA256: `71ef23e341041b8e8254e4e1bd4507729dd10f2c7621540f02f2e1d00a37aacf`
- Interpreter isolated; installed package bytes matched the wheel; application
  source was not added to the test interpreter import path.

Limits: native spawn adapters and consumer recovery have not yet been wired to
the new controller. Container observations here are deterministic test ports;
OS exclusion is real. No Linux/macOS execution or full M2 crash matrix is claimed.
Global install and consumer vendor wheels remain M1; no user restart occurred.
