# Passive discovery repair (2026-10-02)

The installed .53 Core returned no PATH candidates without preapproved roots,
even when Claude was directly executable. The Connector's npm shim fallback
also failed to resolve real Codex and managed Pi payloads on Windows. This
conflated installation observation with local trust selection.

Core .54 observes direct PATH executables and fixed Windows Codex npm and Pi
npm/managed package layouts. It never executes or interprets wrappers. It retains
each full physical installation reference and content identity. Directories on
PATH are not recursively searched; current/relative directories are excluded.
Package metadata reads and the existing Pi dependency identity remain bounded.
Managed Pi current-version cannot traverse directories. Multiple Node targets
remain separate pairs; duplicate PATH directories/targets collapse by reference.

Observed candidates outside approved physical roots have `source=path` and
`trust=untrusted`. Availability includes `selection_required`. Existing prepare
and version-probe trust guards continue to refuse them. Explicit candidate
construction and approved roots keep their existing selection semantics. Merely
finding a package does not prove that a shell alias or custom launcher invokes it.
This release does not add native macOS containment.

Installed wheel tests: Windows/Python 3.13.1: 64 passed; WSL Linux/Python 3.12.13:
59 passed, five Windows-only skips. An additional 15 installed Windows inventory,
reducer and consumer-conformance tests passed. JUnit files are beside this report.
The Windows layout test forbids subprocess creation and proves both visible
untrusted candidates and prepare refusal. npm aliases and managed traversal are
covered. A legacy ambiguity fixture now replaces PATH with its two test roots,
so real installations do not contaminate its exact two-copy assertion.

The installed Connector using this wheel found Codex, Pi and Claude on the real
Windows machine. All three stayed untrusted. Codex/Claude were NOT_PROBED; Pi
0.87.1 was PREPARATION_REQUIRED. No version probe or provider launch was requested.
Pi's full content identity can make the first passive scan noticeably slow;
this is not a performance qualification or an end-to-end runtime acceptance.

Wheel SHA-256:
`e79c4b9ccc5205bd2cfd05f750dbef543d771355e85c6853975f22367d36b9ff`.
Every packaged Python file was compared byte-for-byte with the reviewed source.
The .54 change preserves R4 wire revision/schema. Coordinated consumer adoption
and final G0–G3 qualification remain required.
