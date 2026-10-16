# M2a — Durable launch contract and producer exclusion

2026-10-16. Foundation checkpoint; M2 remains in progress.

The launch record contains immutable session, opening operation, generations,
container and producer identities. CAS transitions allow only one claim, fence
the producer monotonically, and require a separate stop proof. Neither a missing
birth record nor acquiring the OS gate releases capacity or proves termination.
No arguments, environment values or credentials are stored in this contract.

SQLite implements the port on the journal worker. Transactions roll back on
write failure; existing birth evidence must match the claimed launch when one
exists. Historical M1 evidence remains conservative.

The host adapter uses a nonblocking gate per producer: named mutex on Windows,
private persistent flock inode on POSIX. Different producers remain independent.
Windows abandonment grants ownership but still requires rereading durable state,
as specified by [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject).
Acquisition/release stay on the same worker thread, per
[mutex ownership rules](https://learn.microsoft.com/en-gb/windows/win32/sync/mutex-objects).

Validation against the installed wheel: **53 passed**, zero failures/skips,
Windows 11 AMD64, Python 3.13.1. Includes competing journal connections,
transaction rollback, immutable identity, pre-birth claims, actual cross-process
exclusion, process crash and abandoned mutex, journal conformance/disk full.
The isolated interpreter checked installed package bytes against the wheel;
application source was not on its import path. `pip check` passed.

- Wheel SHA256: `f864ebb60dbd45d76e4ac6cc045d6a8980269b9b5925d3d5425005c25e657ee7`
- Local evidence: `build/process-launch-m2a-installed/manifest.json`,
  `build/process-launch-m2a-installed/results.xml`.
- Result SHA256: `e4939f07e9655ac5c44996e396b46905e74e7ba23c29b5ecdb49e313435a1960`

Not yet integrated into runtime spawn or host recovery. Next: atomic launch
intent with admission; planned container identity through all native adapters;
fenced recovery and crash-boundary tests. POSIX execution is not qualified by
the Windows run. Consumers and the live installation still use M1 Core.
