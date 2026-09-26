# Trusted native adapter registry — 2026-09-25

`native/registry.py` now owns the fixed metadata for Codex app-server, Pi RPC,
Claude stream and Claude attach. Discovery derives managed executable names
from that table; the copied-adapter factory consults metadata before resolving
secrets or importing connector modules. `load_adapter` imports only a static
relative module/class from the table after ID and platform checks. Unknown
IDs, arbitrary module paths and incompatible platforms fail with typed
`CoreError` before any import. Attach remains separate from the managed
factory and is not silently instantiated through the Claude stream branch.

The registry's platform list means an implementation may be considered for
that platform, **not** that a native build/provider has been qualified. The
independent exact-build allowlist remains empty. Unit tests use an import spy
to demonstrate metadata-only access, rejected peer-supplied paths, lazy
loading of a known Pi class, and rejection of Windows attach. This is partial
K02.2/TK-09 evidence; host consumer and real-platform qualification remain
`NOT_RUN`.

Verification: `pytest -q` reported `250 passed, 66 skipped`; local wheel/sdist
build and clean-wheel verifier passed after the registry refactor.
