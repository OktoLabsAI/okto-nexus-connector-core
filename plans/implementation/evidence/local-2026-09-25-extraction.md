# Native extraction regression — 2026-09-25

Source Nexus SHA: `7ed52c22865a92c3768bc32508ed9e35dc5efdc3`.
Environment: Windows 11 build 26200, Python 3.13.1, Core local worktree.
Core SHA: no commit yet. Connector SHA: not involved. Provider versions: not run.

Commands (via `rtk`):

```text
python -m pytest -q --tb=line
python -m build --wheel --sdist
python tools/verify_wheel.py
```

Result: 122 passed, 66 skipped in 81.67 seconds. The 66 skips comprise
57 POSIX attach cases, 1 Pi live provider case, 1 Codex live provider case,
and 7 Claude stream live/platform cases. One warning is intentional fault
injection: a Pi reader callback raises in a test that verifies shutdown
notification still reaches consumers. No failure was suppressed.

The wheel installed in a clean temporary venv with `--no-index --no-deps`.
All four copied adapters imported, packaged contract hashes matched, and an
AST scan of every wheel Python module found no imports of `okto_nexus` or
`okto_nexus_connector`. The build and test run used no sibling checkout at
runtime; the Nexus checkout was read only to copy source/tests and provenance.

Artifact hashes:

- wheel SHA-256 `906226aa8d5c27b56782f666cffe8bde0788dfaaca6392d04799e833e85be555`
- sdist SHA-256 `30500365d01a9f4d1e3c60d859348073ee3f3aef8bf89442f1bb625b0a7fb04f`

This is protocol regression evidence. It does not qualify native providers,
the POSIX attach substrate, Linux containment, public async kernel use, or
Server/Connector integration. TK-08 and J27 remain NOT_RUN at their full
prescribed scope.
