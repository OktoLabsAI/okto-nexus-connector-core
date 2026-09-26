# Installation-scoped owned-slot ledger — 2026-09-26

`SQLiteOwnedSlotLedger` is a Core-owned, application-neutral implementation
of the new `OwnedSlotLedger` port. A trusted installation host supplies one
absolute local ledger path and injects handles to that same file into every
`LocalRuntimeCore`, even when each executor uses a distinct technical
journal. The existing journal-local reservation remains the fallback for
synthetic/single-journal use. The host owns ledger lifetime.

The standalone ledger uses SQLite WAL/FULL synchronization and transactional
capacity checks. A durable policy row prevents peers with different limits
from silently sharing a budget on either reserve or release; the default is
eight. Namespace/session
identity and original open operation ID fence reservation and release. A
reservation survives process exit and ledger reopen, is not reused, and is
released only when the live runtime has a proven prelaunch refusal or an
observed native stop. A replacement ledger file is rejected by storage
identity checks. A main-file page ceiling is configured, but a hard WAL/
filesystem bound is not claimed.

Tests used two separate Core runtime journals with one-slot installation
ledger: the second factory was not called until the first session stopped.
An ambiguous first launch pinned that slot across closure/reopen and denied
a launch from the other journal. Three independent Python processes racing
for two standalone-ledger slots yielded exactly two reservations and one
`CAPACITY_EXCEEDED`, retained after abrupt exits. The reusable port/restart
conformance kit passes on this ledger and rejects an adapter that drops
reservations. Ten repeated WSL2/Python 3.11 multiprocess races passed.

Focused runtime/slot/docs suites passed 67 tests in every local Windows/WSL2
× Python 3.11–3.13 environment. Full Python 3.13 suites passed Windows
569/73 and WSL2 628/14 (passed/skipped), with the expected injected legacy
Pi warning.

Normalized Windows and WSL2 builds produced identical artifact hashes:

- wheel SHA-256: `0eababc799041a8d10b755575cdb2cec74ff1174da912de27686e93e8ec03e74`
- sdist SHA-256: `abd8dc2ab55bb8f0216670cb4606ac44eb6983de83f043b8d6d444604e664f8b`

Both artifacts passed strict Twine checks and offline install/resource checks
on Windows and WSL2 with Python 3.11, 3.12 and 3.13. The clean-wheel import,
embedded consumer and remote consumer smokes passed. Release validation
correctly reports `publishable: false` for `0.1.0.dev0`. A source import audit
found no direct `okto_nexus` or sibling-project path injection.

This does not automatically wire the real Server/Connector hosts to a shared
installation path. A clone or replaced store is not a transferable physical
ownership proof; no slot is released by PID-only observation, network
disconnect, timeout or reboot. Actual host integration, independent
containment proof after crash, distributed/multi-machine arbitration and
provider qualification remain open.
