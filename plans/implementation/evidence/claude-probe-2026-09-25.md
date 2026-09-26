# Selected Claude binary observation — 2026-09-25

K03.1/K07.1 partial evidence. On this Windows host, a read-only, bounded
`--version` probe against the explicitly selected local `claude.exe` returned
version `2.1.282`. A bounded PE-header read identified `x86_64`; the selected
executable SHA-256 was
`fc0e3af017705624b9e1bce913f72761864ff994804514da1f5e41380fca4484`.
The probe used a reduced environment without provider or Nexus secrets. It
did not submit a prompt, authenticate to a provider or test native runtime
behavior. The version is **observed, not qualified**; the Core's effective
build set remains empty and the real factory still rejects it before reading
secrets or spawning a managed runtime.

The Core now parses PE, ELF and 64-bit Mach-O architecture from bounded file
headers without executing candidates. Its qualification key requires exact
kind/version/platform/architecture/executable fingerprint, rather than a
version-only allowlist. `LocalRuntimeCore.discover`, `prepare` and `open` move
file hashing/path realization off the host event loop. Tests cover header
parsing, a selected synthetic version probe, drift and matrix mismatch.

Verification on Windows/Python 3.13:

- `pytest -q tests/test_discovery_probe.py tests/test_profiles.py
  tests/test_runtime.py tests/test_native_runtime_bridge.py`: 20 passed.
- `pytest -q`: 195 passed, 66 skipped.
- `python -m build --wheel --sdist`: passed.
- `python tools/verify_wheel.py`: clean installation/import, bundle hashes and
  no Nexus/Connector imports in packaged Python passed.

SHA-256: wheel
`81a6d584fa146518ae5220237c8dc7a18b514f1e08b0b938afba957b6755b1d9`;
sdist `fd4f5f6153e7e87ac4648261a2294adc679a5665d865a1b75ea4e2590fe7c9d9`.

`pi` was not found on this host's PATH; `codex` resolved to a PowerShell
wrapper, which the Core intentionally does not launch as a trusted binary.
No provider-real handshake, multi-turn/control/HITL or Server/Connector
integration gate was exercised. K05–K08 and TK-21–TK-32 remain NOT_RUN at
their full required scope.
