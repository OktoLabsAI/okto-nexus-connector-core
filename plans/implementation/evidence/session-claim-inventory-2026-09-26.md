# K04 durable session-claim inventory - 2026-09-26

After restart, `inspect` correctly reports unknown ownership for a session
without a local binding, but a host previously needed to know every session ID
in advance to call it. The SQLite journal now exposes `claimed_sessions` for a
Server/executor namespace. Each page contains the durable session key and
original open operation ID. The first page fixes a high-water rowid; subsequent
pages use that watermark and the returned cursor, excluding claims admitted
later. Claims are immutable and are not deleted by close or safe failure.

The RuntimeCore and Journal ports, public value types, API/lifecycle guides,
and reusable Journal conformance kit include this read-only operation. The
runtime validates namespace and bounded page parameters before delegating to
an injected host journal. SQLite tests cover paging, restart between pages,
new claims after the watermark, namespace isolation, invalid inputs, and the
host-port validation fence. No code imports the sibling Nexus application.

Focused tests passed on Windows and WSL2, Python 3.11-3.13 (66 each for the
session claim, conformance, public docs and runtime files). Full Python 3.13
suites passed: Windows 510 passed/73 skipped; WSL2 569 passed/14 skipped.
Both emitted only the expected legacy Pi test's deliberately injected thread
exception warning.

Normalized Windows and WSL2 artifacts matched byte-for-byte: wheel SHA-256
`f2d5a424d72b5e1e553c323ca301eabe7403383afeeb87e4591a757382b1ac67`;
sdist SHA-256
`d23cf8762271c81d087bcb3b1994a2f9e659421ea7f29492cf6bd16febc26dc8`.
Strict Twine and clean-wheel embedded/remote consumer smokes passed. Release
validation returned `publishable:false` for development version 0.1.0.dev0.
Windows offline wheel/sdist installation and bundled-resource checks passed.

This is a bounded history of claimed IDs, not evidence of an active process,
physical ownership, lease continuity, or a safe takeover after restart. The
actual Server journal adapter has not run the conformance kit; cross-host
reconciliation and real-provider qualification remain open.
