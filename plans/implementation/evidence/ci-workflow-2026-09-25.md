# K00/K11 CI preparation — 2026-09-25

`.github/workflows/core-ci.yml` adds read-only validation on push, pull
request and manual dispatch. Six test jobs cover Ubuntu 24.04 and Windows 2022
with Python 3.11, 3.12 and 3.13. Each job installs the Core with its test
extra, checks generated-contract parity, runs the full test suite, builds the
wheel/sdist and verifies clean-wheel imports/resources. A dependent Ubuntu
job builds a runtime-dependency SBOM from the installed wheel and retains the
development artifacts for review. No release, PyPI publication, external
product mutation or repository secret is used.

The official `actions/checkout` v7.0.1, `actions/setup-python` v7.0.0 and
`actions/upload-artifact` v7.0.1 commits are SHA-pinned. Local YAML parsing
verified triggers, read-only permissions, job dependency and the OS/Python
matrix; `contracts/generate.py --check` passed.
Windows/Python 3.13 and Ubuntu WSL2/Python 3.12 full source suites, local
wheel/sdist builds and clean-wheel verification have passed separately, as
recorded in status. The seven hosted CI jobs have **not run** because this Core
worktree has no configured remote/runner.

This is CI preparation, not a protected release workflow. Branch protection,
required checks, signed artifact provenance, transitive license review, real
provider qualifications, and publication approval remain K00/K11 gates.
