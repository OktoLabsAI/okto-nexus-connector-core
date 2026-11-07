# Observe Codex thread configuration without changing execution

The adapter previously discarded policy and instruction-source metadata in the
existing thread/start and thread/resume replies. A session now retains a bounded
allowlist of that response; its normal event pump emits the Core-originated
lifecycle event core/codex_thread_configuration before consuming native events.
The event carries canonical server/executor/session/epoch correlation, and passes
through secret redaction before the journal. No extra RPC or policy change occurs.

Model, provider, reasoning effort, working directory, approval policy/reviewer,
sandbox and instruction-source paths remain explicitly reported, missing or
invalid. Unknown policy members, excessive values and redacted fields cannot
be mistaken for a complete effective setting. No transcript or instruction
content is copied; the complete payload is bounded at 48,000 bytes.

126 unique source cases and the same 126 installed cases passed, including
40 new identities. Three initial synthetic handshake-fixture failures remain
in the evidence; they are not counted as qualification. All 167 package files
match source, wheel and installation. Independent review found no blockers;
five pre-existing Ruff diagnostics are unchanged.

Unpublished wheel SHA-256:
609e0fbbb20855c6b788d2523b0aeb6cdfbf4b3f5c9792c9e4a080284729c9dd.
This is installed synthetic qualification. Reported response metadata is not
proof of provider enforcement, useful work or completed DX-T43/M1 acceptance.
No native provider, personal credentials or OS service was used.
