# K01.4/K01.5 offline consumer bundle verification — 2026-09-25

`nexus_connector_core.conformance.verify_contract_bundle` lets a consumer
verify an installed wheel without a source checkout or network access. The
consumer supplies a reviewed manifest SHA-256 and expected NXL revision. The
function checks the manifest pin, every declared resource hash, schema
validity, positive/negative frame and model fixtures, and JCS hash vectors.
It returns an immutable count/report and fails closed with
`CONTRACT_MISMATCH` on a divergence. The same check is available as
`python -m nexus_connector_core.conformance --manifest-sha256 ...`.

The current `0.1.0.dev0` manifest is explicitly `development-partial`; a
consumer must opt in with `allow_development_partial=True` or the equivalent
CLI flag. The independently pinned development manifest SHA-256 is
`sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630`.
This is a development pin, not a release compatibility promise. Changes to
the bundle require intentional downstream repinning, not silent acceptance.

Unit tests cover successful verification, wrong pin/revision, default partial
refusal, altered bundled-resource rejection and CLI output. The clean-wheel
verifier also runs the pinned check
inside a fresh virtual environment, proving package resources are available
without local source imports. Actual EmbeddedHost/RemoteHost and Nexus/
Connector integrations remain unqualified; no consumer application was
modified or claimed compatible by this smoke test.
An isolated Ubuntu WSL2 invocation of the installed wheel reported 9 files,
49 frame fixtures, 17 model fixtures and 3 JCS vectors checked.

Local development artifact SHA-256 values: wheel
`4781686351717554ee97ba67a8ff2a40eaa9965bdfbac0e6f92f9233d40df2a1`;
sdist `de4cfeb1a850d95eb1a54c755fed9099ab80439f9b87f8d22cf018899f250298`.
