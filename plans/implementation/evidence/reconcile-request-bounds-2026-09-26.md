# K04 bounded reconciliation request - 2026-09-26

The Core runtime's read-only `reconcile` path previously accepted an
unbounded number of identifiers even though the bundled NXL
`reconcile.request` frame caps each distinct operation/session ID list at
256 and each ID at 160 characters. A trusted host could therefore create an
unbounded serial journal read or pass malformed in-process input.

`LocalRuntimeCore.reconcile` now checks the request type, Server/executor
namespace, tuple-typed ID lists, 256-item maximum per list, 1–160-character
ID length, and uniqueness before any journal lookup. Larger recovery scans
must be batched. The test reads the bundled schema to guard the numerical
bounds and uniqueness contract against drift. Invalid requests are proven to
make zero host journal calls; a 256-operation request preserves result order.

Focused runtime/reconcile tests passed on Windows and WSL2 Python 3.11–3.13.
Full Python 3.13 suites passed: Windows 524 passed/73 skipped and WSL2
583 passed/14 skipped. Both emitted only the expected deliberately injected
legacy Pi thread warning.

Normalized Windows/WSL2 builds matched byte-for-byte: wheel SHA-256
`8eab5d00554a8ae8f8de4b23369ac9eb225abad1666633762a2f9cdb0d63a069`;
sdist SHA-256
`43de0cb26b02f54dcfe44e3f98e319f59f52a439728d87e2a2ea0670c6bdfe87`.
Strict Twine, clean-wheel embedded/remote consumer smokes, and Windows
offline wheel/sdist installation/resource checks passed. Development release
validation returned `publishable:false`; no publication was attempted.

This does not validate the actual Server host adapter, process ownership
after restart, or real-provider reconciliation.
