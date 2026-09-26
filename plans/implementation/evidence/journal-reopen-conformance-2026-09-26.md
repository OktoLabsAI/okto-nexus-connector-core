# K04/TK-41 journal reopen conformance kit - 2026-09-26

The reusable Journal-port kit previously exercised behavior on one adapter
instance but did not test durability across adapter close/reopen. A new
`run_journal_restart_conformance(open_journal)` scenario opens the same
caller-owned private backing store three times through an async context
manager factory. It verifies that an admitted open's effect marker, exact
idempotent receipt, session-ID claim/conflict, allocated event sequence,
replay, contiguous watermark and durable ACK survive reopen boundaries.

The SQLite reference passes. A deliberately ephemeral host-style factory
that opens a new backing store each time fails at the lost effect marker,
showing that the kit detects this class of adapter defect. The factory and
cleanup are supplied by the host; no application database, Nexus import or
native process is used by this Core-owned test kit.

Focused conformance/public-doc tests passed on Windows and WSL2 Python
3.11–3.13. Full Python 3.13 suites passed: Windows 526 passed/73 skipped;
WSL2 585 passed/14 skipped. Both had only the expected legacy Pi test's
deliberately injected thread-exception warning.

Normalized Windows/WSL2 artifacts matched: wheel SHA-256
`c8df78f8165708bc4db717666efaf7f24e1ebbfb6b4b5091368a9096d9eb640b`,
sdist SHA-256
`ec330b7faa08417dd011fe98b057e51c0284c1f0251be965d210662a3b576cee`.
Strict Twine, clean-wheel embedded/remote consumer smokes and Windows
offline wheel/sdist installation/resource checks passed. The development
release remains `publishable:false`.

This is reopen behavior, not a process-kill/power-loss campaign. The actual
Server host journal adapter has not run either conformance kit; TK-41 and
the full K04/TK-37 durability gate remain open.
