# Codex 0.159.0 exact Windows qualification and R4 native probes

Date: 2026-09-30. Core: 0.2.31.dev0.

The user-authorized native campaign completed app-server handshake, an ordinary turn, targeted steer, and targeted interruption. Qualification is limited to conversation and controls on the exact recorded Windows/x86_64 executable fingerprint or portable build identity. No approval/input qualification is added. Changed versions, platform, architecture and bytes remain refused.

The final installed wheel was compared byte-for-byte with source before real factory probes. Codex opens, completes a correlated turn, and persists a SUCCEEDED receipt. The extended probe also installs R4 lease authority before launching actual Codex, Pi and Claude; all three produced a successful correlated turn. These grants are constructed locally for Core tests, not issued by a Nexus Server journey.

## Results

- Directed qualification/discovery tests: 24 passed.
- Full installed Core suite: 951 passed, 74 skipped, three warnings.
- Pi R4: close SUBMITTED, shutdown already_closed.
- Codex and Claude R4: close OUTCOME_UNKNOWN, shutdown already_closed.
- Codex active shutdown probe: 4.17 seconds, outcome unknown, late submit refused, turn receipt CANCELLED with possible effect retained. The probe does not independently establish active generation or process-stop confirmation.

## Reproduction and artifacts

Run tools/probe_managed_factory.py with the explicit adapter paths and --r4 for R4 authority. Exact commands are in the adjacent JSON evidence. The wheel hash and build staging path are in codex-0159-artifact.json. Source test imports use the repository root for tests/tools only; product imports are verified in site-packages.

Initial build lacked setuptools in the test environment and was rebuilt using system Python. Initial installed test collection traversed outside the repository; the next attempt could not import tests/tools. The final run sets rootdir/confcutdir and adds only the repository root. Initial XML evidence is preserved. The first wheel used old __version__; the final wheel synchronizes package metadata and public version, with separate manifests.

## Remaining acceptance

Close/shutdown classification, Server-issued authority journeys, protected provider login configuration, Windows/Linux coverage and remote hosts remain open. This exact build grant does not close M01/M05/M06/M11/M13 or release gates.
