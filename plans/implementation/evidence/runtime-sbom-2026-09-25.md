# K00/K11 runtime dependency SBOM — 2026-09-25

`tools/generate_sbom.py` installs the built Core wheel into a clean temporary
target venv, removes bootstrap `pip`, then runs pinned `cyclonedx-bom==7.3.1`
from a separate generator venv. It strips inherited Python path/home/venv
variables, asks the generator to validate a reproducible CycloneDX 1.6 JSON
document, and checks that the Core, `jsonschema`, `rfc8785` and direct
dependency relationships are present. It rejects generator/build tools in
the target inventory. The script does not alter runtime dependencies.

Local Windows/Python 3.13 generation passed: Core plus six runtime packages
(`attrs`, `jsonschema`, `jsonschema-specifications`, `referencing`, `rfc8785`,
`rpds-py`). Ubuntu WSL2/Python 3.12 generation also passed: its environment
resolved one additional Python-conditional package, `typing_extensions`. The Windows
development wheel SHA-256 was
`40cb8e950cab0403fd7aa5f7e2c464410800c1e144e040e2b871b30c68b4f128`;
its local SBOM SHA-256 was
`af3f0770ed028460693f82fd7292a606c1c7b28e9d2cbbfc81f6efb186a657cf`.
The WSL2 SBOM SHA-256 was
`f15a9517eae63a941784225f03952583f1e26e04547a3989f75e0b54b5e90d02`.
The Windows SBOM hash did not change after a wheel rebuild because it
describes installed package metadata/dependencies, not the wheel's source
bytes; the two hashes must therefore be retained together. They bind this
local build only, not a release.
Two consecutive local Windows builds and one WSL2 build with
`tools/build_artifacts.py` produced identical wheel and sdist hashes;
see `reproducible-build-2026-09-25.md`.
The SBOM was regenerated against the wheel hash above. This does not establish
independently reproducible release builds across the full toolchain matrix.

The read-only CI workflow now has a dependent Ubuntu SBOM job and retains the
wheel, sdist and SBOM as short-lived development artifacts. No hosted CI job
has run yet. The output is one resolved installation inventory, not proof of
all possible dependency resolutions. License values come from package
metadata and have **not** been legally reviewed against bundled license text
or the Core's custom license. Signing, release provenance and protected
publication remain pending.
