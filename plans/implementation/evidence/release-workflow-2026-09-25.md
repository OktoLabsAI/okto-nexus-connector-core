# K11 protected release workflow — 2026-09-25

The Core now owns `.github/workflows/core-release.yml` and
`tools/validate_release.py`. No code is imported from the sibling Nexus tree.
The manual workflow builds and tests on Ubuntu/Python 3.13, checks generated
contracts, verifies an isolated installed wheel and two synthetic consumers,
runs strict Twine metadata validation, records a runtime SBOM, and uploads only
the checked wheel/sdist for a separate publication job. All third-party action
references are pinned to commits. The publish job is main-only, requires the
`pypi` environment and grants OIDC only there. It compares the downloaded
distribution filenames and SHA-256 bytes with reviewed values before PyPI
upload with attestations.

For `publish=true`, the caller must supply a stable `X.Y.Z` version and both
reviewed SHA-256 inputs. The `pypi` environment must contain secrets
`CORE_RELEASE_APPROVED_COMMIT` and `CORE_LICENSE_REVIEWED_COMMIT` equal to the
workflow commit and `CORE_RELEASE_APPROVED_VERSION` equal to the release
version. Missing or mismatched values fail closed. The environment must also
be configured with required reviewers/branch protection; the secrets are a
guard, not a substitute for that GitHub configuration. A matching PyPI trusted
publisher must be registered for this repository, workflow and environment.

Local checks on the `0.1.0.dev0` candidate: strict Twine check passed for both
distributions; the release validator passed only with `--allow-development`
and reported `publishable: false`. Without that switch, the candidate is
rejected. The validator's synthetic unit tests and the workflow static test
passed. Full local suites on Python 3.11–3.13: Windows, 420 passed/73 skipped
per version; WSL2, 479 passed/14 skipped per version. The installed-wheel import/consumer smokes passed
on both systems. The current candidate wheel SHA-256 is
`f465c9355d8149b0559c8b3e6ed863bcab4ee44571b2af68e3e83a30a04a463f`;
sdist SHA-256 is
`aefa9555bacb8accc9c5094758b4772fe5fa1ee20e49e6550576ed2133a72e6e`.
Windows and WSL2 builds matched byte-for-byte for both artifacts.

The hosted workflow has **not** run. This is a development-partial contract
bundle, not an approved stable release. Legal/license review, protected
environment setup, PyPI trust configuration, independent builder/provenance
review, real consumer/provider integration and a stable release decision are
still open. No PyPI publication was attempted.

The 2026-09-26 runtime-sink revision refreshed the local candidate. Strict
Twine and development-mode release validation passed for the intermediate
wheel SHA-256 `b8d55fb2b2758424ffcb3fc60cec152c8cddc76e86831fde254059716e9f054d`
and sdist SHA-256 `016714d964567e06933b50bcda34114c0d9394192089441c1447142413ed5537`;
the validator still reports `publishable: false`. Windows and WSL2 Python
3.13 builds matched. The preceding hashes and six-version suite counts above
are retained as historical evidence, not current-artifact qualification.
The final wording correction changed only comments/documentation, yielding
matching Windows/WSL2 wheel
`52e51b2299f72693d3f6d3deecb562a8463de11e33dd0a286d247071e5a55a6b`
and sdist
`03428288b96e63876bb3fe37f93a6a5cf27fd5c769462b4f13607530266c178d`;
strict Twine and development-mode release validation also passed for these
final bytes (`publishable: false`). The clean-wheel verifier and Windows
Python 3.13 offline wheel/sdist installations passed.

For the subsequent Server/executor quota revision, Windows/WSL2 Python 3.13
builds matched at wheel SHA-256
`e5f08617c4681edfcdfb79da3b58c30454bf9e90e8c43ff2818cf00b952f4fc0`
and sdist SHA-256
`025e31e617eb0d56673151bf8bbcc67a25ed1cf6337ab408adcc62dbc11b2511`.
Strict Twine, clean-wheel consumer checks, offline Windows installation and
development-mode release validation passed; it remains `publishable: false`.

For the subsequent event-recovery revision, strict Twine, clean-wheel
consumer verification, Windows Python 3.13 offline installation and
development-mode release validation passed for wheel SHA-256
`1218812c90bcf97a9a873762ab9d543adea66f04347395419a2a78b0bda051df`
and sdist SHA-256
`1786329577618aad75f4f7166baba1a86647a211e5619a49f25dc6f2b5fc8f36`.
Windows/WSL2 Python 3.13 builds matched; `publishable` remains false.

For the logical-quota recovery revision, strict Twine, clean-wheel consumer
verification, Windows Python 3.13 offline installation and development-mode
release validation passed for wheel SHA-256
`717b1c63124a49bd8fdca2330f917f279fc15ff5e6ab2550bced13029782bca0`
and sdist SHA-256
`cebf80190e693b5c2f98610023f14db0addf6d867162b27587adb850ac1322ce`.
Windows/WSL2 Python 3.13 builds matched; `publishable` remains false.

The subsequent sink-race revision passed strict Twine, clean-wheel consumer
verification, Windows Python 3.13 offline installation and development-mode
release validation for wheel SHA-256
`220236571181ebad7327e6c6a93b7b113422e2978d1c6acdfbd2605df4c5d680`
and sdist SHA-256
`a5995c440371a1ae7fa8a0e5e59601d0555a4364e53257d5631428960f49ab2c`.
Windows/WSL2 builds matched; `publishable` remains false.

The global-operation-counter revision passed strict Twine, clean-wheel
consumer verification, Windows Python 3.13 offline installation and
development-mode release validation for wheel SHA-256
`1580cb76787b72516d951a79d3b77b9b9da7b40da8fb31d5325f3526ce4f26ad`
and sdist SHA-256
`49b71004a17fc3ff48e1f487b73d5640bdcbca5bc2d5058fe6e6dd660f73669f`.
Windows/WSL2 builds matched; `publishable` remains false.

The subsequent hostile-configuration revision passed strict Twine,
clean-wheel consumer verification, Windows Python 3.13 offline installation
and development-mode release validation for wheel SHA-256
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`
and sdist SHA-256
`98cb2d399e15e3d90f2f128fa2f4bfd76234ebf0b32edf6877fe2362d6e31575`.
Windows/WSL2 builds matched; `publishable` remains false.

The subsequent reusable-probe revision passed strict Twine and
development-mode release validation for unchanged wheel SHA-256
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`
and updated sdist SHA-256
`22fb59f4fc367090a2418e66dbeb044ec40b9133e441f0917af644935bdb4d43`.
Windows Python 3.13 offline wheel/sdist installation passed; Windows/WSL2
builds matched and `publishable` remains false.

The process-fairness/fixture-packaging revision passed strict Twine,
clean-wheel consumer verification, Windows Python 3.13 offline wheel/sdist
installation and development-mode release validation. The wheel remains
SHA-256 `f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`;
the sdist is SHA-256
`6804aafa0cb14bc03955b56b173e379689aa188f2deeeb4c909a09f8c298fa4d`.
Windows/WSL2 Python 3.13 builds matched and `publishable` remains false.

The native hostile-JSON boundary revision passed strict Twine,
clean-wheel consumer verification, Windows Python 3.13 offline wheel/sdist
installation and development-mode release validation. Windows/WSL2 builds
matched: wheel SHA-256
`a5c1523b879d78c5ee38164012a6bd94ef9f5b8289f96e5580f3c8ce4469b96d`,
sdist SHA-256
`a86d04cda36b702259d959270996268989b66faa3852175cee3f005a2d90df8a`.
`publishable` remains false.

The Unicode/streaming-bounds revision passed strict Twine, clean-wheel
consumer verification, Windows Python 3.13 offline wheel/sdist installation
and development-mode release validation. Windows/WSL2 builds matched: wheel
SHA-256 `2ae84d202dd14cc53fcb9acbea8a1c3e0255ff7304a04e02417b48298739e3d5`,
sdist SHA-256
`caea683c135bcbb9f39ede620ac54fd9a1f42844fa13a85332b5aebfd4e94533`.
`publishable` remains false.

The Pi byte/LF framing revision passed strict Twine, clean-wheel consumer
verification, Windows Python 3.13 offline wheel/sdist installation and
development-mode release validation. Windows/WSL2 builds matched: wheel
SHA-256 `6a0aa4caff004f9d7eda36fb3a4e4f366953f2454bdd38e03b496a5845b69c95`,
sdist SHA-256
`def2ae4bd8a1716fa0447cd2d7c2612e3164bb52fa60a29fc9946433f321a8ad`.
`publishable` remains false.

The Pi response-correlation fence revision passed strict Twine, clean-wheel
consumer verification, Windows Python 3.13 offline wheel/sdist installation
and development-mode release validation. Windows/WSL2 builds matched: wheel
SHA-256 `10b5b0385ea0dbface89a88d8c816a87720317797ae0c3b7c1417020de66e7a5`,
sdist SHA-256
`cf392f422a3336682063cd6467b4cc653fc877c733ca99125fe631bd2ea0012f`.
`publishable` remains false.

The native-history fairness revision passed strict Twine, clean-wheel
consumer verification, Windows Python 3.13 offline wheel/sdist installation
and development-mode release validation. Windows/WSL2 builds matched: wheel
SHA-256 `ccec3e29b299069d3744ae46995c903097a185aa42f48455bcdaf9340db14b78`,
sdist SHA-256
`9a88d7a90c9873603acb6ebbd45dcdbe5496073c24e7c96036e85f9c250cdb25`.
`publishable` remains false.

The Codex slow-subscriber isolation revision passed strict Twine,
clean-wheel consumer verification, Windows Python 3.13 offline wheel/sdist
installation and development-mode release validation. Windows/WSL2 builds
matched: wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`2fbff8ba154c08c068a0585dd9cc5f39d6660590edcb30ad5ccc8c7518b45da6`.
`publishable` remains false.

The follow-up native stdout-flood/urgent-control test revision passed strict
Twine, clean-wheel consumer verification, Windows Python 3.13 offline
wheel/sdist installation and development-mode release validation. Builds
matched across Windows/WSL2: wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`8d41b67f41baf8b8a45f28c58a74570e11f8ec84c2fe2701ba5cab78106bb3db`.
`publishable` remains false.

The shared-history pressure test revision passed the same local strict
Twine, clean-wheel consumer, Windows offline wheel/sdist and development
release gates. Windows/WSL2 builds matched: wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`1ad6d9ea0c7aa74e429ed677145f963fda9e6bc6c519d6a770d7cb6cd12620b5`.
`publishable` remains false.

The multi-session byte-fairness Core fix passed local strict Twine,
clean-wheel consumer, Windows offline wheel/sdist and development release
gates. Windows/WSL2 builds matched: wheel SHA-256
`360b0b02df671230dc4ede62a31b8bd801c36c64b4e3eb3c610320c31b11d562`,
sdist SHA-256
`e60817cec8caf884f1d19e47fce006dc18a343460638598aa1b5b40d1ed758bc`.
`publishable` remains false.

The large-incoming-event replay preflight revision passed local strict
Twine, clean-wheel consumer, Windows offline wheel/sdist and development
release gates. Windows/WSL2 builds matched: wheel SHA-256
`43c78dfae685052830df647df3b7afdb64d318e322009ee4f0fc79bc6b251915`,
sdist SHA-256
`8378660e9d38e94b8ad19b5df51f443a3895da4de5ffd217d18814884c58d7c9`.
`publishable` remains false.

The bounded journal-compaction revision passed local strict Twine,
clean-wheel consumer, Windows offline wheel/sdist and development release
gates. Windows/WSL2 builds matched: wheel SHA-256
`6a40a33ee9b2664c609066c80fadc5529da4d5eaf8c34e50589c11b5eeb7f514`,
sdist SHA-256
`e996306abd7da5078e8ce8c2691592638e98e13385a9287d545396efa5896f5d`.
`publishable` remains false.

The durable session-claim revision passed local strict Twine,
clean-wheel consumer, Windows offline wheel/sdist and development release
gates. Windows/WSL2 builds matched: wheel SHA-256
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`,
sdist SHA-256
`529886b5f79907d746270db8a3e55f10b2665f63944f5b3c81e717345de7fc78`.
`publishable` remains false.

The two-process session-claim test revision passed local strict Twine,
Windows offline wheel/sdist installation and development release validation.
Windows/WSL2 builds matched: unchanged wheel SHA-256
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`,
sdist SHA-256
`1b0a6ddedf0893ad5c934da2c8a6b00b7731b100dc61a2df63941314a75584bc`.
The byte-identical wheel retains the preceding clean-wheel consumer result;
`publishable` remains false.
