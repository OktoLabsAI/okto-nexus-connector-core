# Read-only owned-slot inventory — 2026-09-26

The Core-owned `OwnedSlotLedger` port and both SQLite implementations now
expose `owned_slot_page`. It returns only unresolved reservations, with
Server/executor/session identity and the original open operation ID. Pages
are bounded to 1–4096 rows and a fixed row-ID high-water mark excludes later
inserts from a scan. Policy drift is rejected on reserve, release and page.

This inventory is deliberately read-only. A reservation can outlive its Core
process, and a missing row may mean a release occurred between pages. The
page is not an atomic point-in-time snapshot, process liveness proof, lease,
or permission to signal a PID or release a slot. The trusted host still needs
independent containment evidence before resolving an ambiguous crash.

The port conformance kit checks pagination, original operation identity,
invalid bounds, release visibility and restart persistence. The journal and
standalone ledger tests cover policy drift and a cross-process crash race;
on reopen the page reports the two winning reservations. Focused tests passed
in local Windows/WSL2 × Python 3.11–3.13 environments (13 tests each). The
WSL2 Python 3.12 virtual environment contained an older installed wheel, so
its source-tree test run explicitly used `PYTHONPATH=src`.

Full Python 3.13 suites passed on Windows (570 passed, 73 skipped) and WSL2
(629 passed, 14 skipped), each with the expected injected legacy Pi warning.
Normalized Windows/WSL2 builds produced identical artifacts:

- wheel SHA-256: `7156d8519feea5f8b6ee2ae4a2a9301c47b9f9d32b40f8d287292ab05ac5c2ce`
- sdist SHA-256: `d3202edb6a57da7be260854eaa093d965f1493cf49f88e8041b8f79f004be279`

The pair passed strict Twine, clean-wheel import and embedded/remote consumer
smokes, and offline wheel/sdist installation on Windows and WSL2 with Python
3.11–3.13. Development release validation returned `publishable: false`.

Real host wiring, authoritative physical reconciliation after crash and
provider/platform qualification remain open.
