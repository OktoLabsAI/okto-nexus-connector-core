# K09.4 native-event redaction — 2026-09-25

The Core owns `native/redaction.py`, adapted from the read-only Nexus
`harness/secret_redaction.py` baseline. It does not import Nexus. The selected
adapter factory builds a session-scoped redactor from approved child credential
values. Both the copied-adapter event pump and the independent event ingestor
scrub native events before translation, durable journal append and publication.

The boundary masks sensitive-key fields and known credential literal/JSON/repr
variants, plus `nxs_`, `nxsept_`, `sk-` and Bearer-shaped values. For
`output_delta`, it withholds every raw native payload string, including unknown
vendor fields, and exposes only normalized `output_text` with a bounded
holdback that catches secrets split across chunks. Pending text is flushed at
turn terminal. Oversized raw native events and excessive credential/pending
state fail closed with `CoreError`.

Tests cover split known and generic credentials, nested sensitive keys,
unknown vendor fields, bounds, scoped factory injection and journal persistence.
The clean-wheel check imports the Core-owned redactor. The full Windows and
Ubuntu WSL2 suite counts are recorded in `../status.md`.

Final local development artifacts after this change: wheel SHA-256
`e4768de673bab10b53910f250bc451fa15646738ed7dfe5f78474ad77740a39c`;
sdist SHA-256
`1a5e62cd865682a93f7f15e63139266e4ab2bfe805bd16558380a021a60a4ca9`.

This is local synthetic evidence, not qualification of real provider output.
Provider-home credentials not supplied to the redactor cannot be masked by
literal matching unless they fit a generic pattern. Non-`output_delta` native
diagnostics receive static field/value masking but not cross-event holdback.
Unknown provider event formats and host wiring still need qualification; no
claim is made that arbitrary future secret forms are detectable.
