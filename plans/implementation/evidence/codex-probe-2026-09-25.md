# K03 selected Codex version observation — 2026-09-25

The [official Codex documentation](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)
uses `codex --version` to confirm the installed CLI version. On this Windows
host, `PATH` resolves npm PowerShell/cmd/sh wrappers. Core discovery continues
to reject those wrappers. A native `codex.exe` inside the local npm Codex
platform package was selected explicitly; its SHA-256 was
`ed1c7b36e44536809c868864c833af8a857f56599a7a7fe23b908a1ba1093b1f`.

`discovery.probe_selected_codex` uses the selected absolute executable only,
checks its SHA-256 and PE architecture before the probe and its hash again
afterwards, filters the environment, and calls the Core-owned bounded process
observer with `--version`. The parser accepts only a narrow
`codex-cli MAJOR.MINOR.PATCH` line. The real local probe returned `0.157.0`,
`x86_64`, `selected`; the Core passed no credential in the probe environment
and made no app-server handshake or model request. Filesystem reads inside the
CLI were not traced. The result is an observation, not a native capability grant:
`QUALIFIED_BUILDS` remains empty.

Focused tests pass on Windows/Python 3.13 (8) and WSL2/Python 3.12 (7 passed,
one Windows-wrapper-policy skip), covering sealed environment, drift, narrow
parsing, wrapper rejection and no capability grant.
The full local suites passed with 367 tests on Windows and 421 on WSL2,
with expected skips and one legacy Pi fault-injection warning per host. The
normalized wheel passes isolated installation checks on both hosts; two
Windows builds and one WSL2 build produced identical wheel/sdist hashes as
recorded in `reproducible-build-2026-09-25.md`.
This does not qualify Codex app-server protocol behavior or any other native
build/platform, and it does not authorize automatic resolution of npm wrappers.
