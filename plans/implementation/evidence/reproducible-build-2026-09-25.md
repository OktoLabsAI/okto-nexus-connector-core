# K00 local artifact repeatability — 2026-09-25

An ordinary wheel-only rebuild changed its SHA-256 from
`2adfdb0de1b8d6f970a3de2bf2638cd80548d2b1a38a68adf78255c09ab52922`
to `c14862fb0aba6872a176c614e558a3894547b337d77da38c26440066bbb3b89f`
without a source edit. Archive timestamps were the immediate source of this
local instability. Setting `SOURCE_DATE_EPOCH` alone stabilized the wheel but
not the sdist, whose tar members retained filesystem/build-time mtimes.

`tools/build_artifacts.py` now fixes `SOURCE_DATE_EPOCH` to 2026-01-01 UTC;
normalizes generated metadata line endings, wheel ZIP attributes and `RECORD`,
and sdist tar/gzip timestamps, modes and owner metadata. The local CI workflow
uses this entry point in both jobs. The current tree was built on local
Windows and Ubuntu WSL2 with Python 3.11, 3.12 and 3.13; all six builds
produced identical SHA-256 values:

| Artifact | All three Windows builds | All three WSL2 builds |
| --- | --- | --- |
| wheel | `f465c9355d8149b0559c8b3e6ed863bcab4ee44571b2af68e3e83a30a04a463f` | same |
| sdist | `aefa9555bacb8accc9c5094758b4772fe5fa1ee20e49e6550576ed2133a72e6e` | same |

Read-only member comparison of each Windows/WSL archive pair reported no
differences. The resulting wheel passed `tools/verify_wheel.py` in isolated
installations on Windows and WSL2.
The sdist includes the build, consumer-smoke, release-validation and offline-install entry points plus five public guides. All 148 sdist members have the
canonical timestamp and zeroed owner IDs/names.
The full local suites passed on each Python 3.11–3.13 environment: Windows,
420 passed and 73 skipped; WSL2, 479 passed and 14 skipped. Each had one expected warning
from the legacy Pi test that deliberately raises inside a reader thread.
This demonstrates equality only for this local Windows/WSL2 × Python
3.11–3.13 matrix and this source tree. Build frontend/backend versions are not
locked, independent builders and hosted CI/release
provenance have not run.

After the 2026-09-26 runtime sink change, a Windows/WSL2 Python 3.13 rebuild
of the updated tree again matched byte-for-byte: wheel SHA-256
`52e51b2299f72693d3f6d3deecb562a8463de11e33dd0a286d247071e5a55a6b`,
sdist SHA-256
`03428288b96e63876bb3fe37f93a6a5cf27fd5c769462b4f13607530266c178d`.
The earlier six-environment hashes above refer to the preceding source tree;
the updated tree has not yet been rebuilt on Python 3.11 and 3.12.

After adding the Server/executor operation quota, Python 3.13 Windows and
WSL2 builds of the newer tree also matched: wheel SHA-256
`e5f08617c4681edfcdfb79da3b58c30454bf9e90e8c43ff2818cf00b952f4fc0`;
sdist SHA-256
`025e31e617eb0d56673151bf8bbcc67a25ed1cf6337ab408adcc62dbc11b2511`.
This is the current local artifact pair; 3.11/3.12 rebuilds of this tree
remain unverified.

After extending physical recovery to both event-write APIs, the latest local
Windows/WSL2 Python 3.13 builds again matched: wheel SHA-256
`1218812c90bcf97a9a873762ab9d543adea66f04347395419a2a78b0bda051df`
and sdist SHA-256
`1786329577618aad75f4f7166baba1a86647a211e5619a49f25dc6f2b5fc8f36`.
The earlier hashes in this file are historical revisions.

The logical-quota recovery revision is now the current local artifact pair.
Windows and WSL2 Python 3.13 builds matched byte-for-byte: wheel SHA-256
`717b1c63124a49bd8fdca2330f917f279fc15ff5e6ab2550bced13029782bca0`,
sdist SHA-256
`cebf80190e693b5c2f98610023f14db0addf6d867162b27587adb850ac1322ce`.

After the sink-race correction, the current Windows/WSL2 Python 3.13 pair
again matched byte-for-byte: wheel SHA-256
`220236571181ebad7327e6c6a93b7b113422e2978d1c6acdfbd2605df4c5d680`,
sdist SHA-256
`a5995c440371a1ae7fa8a0e5e59601d0555a4364e53257d5631428960f49ab2c`.

After adding the global operation counter, the current Windows/WSL2 Python
3.13 builds matched: wheel SHA-256
`1580cb76787b72516d951a79d3b77b9b9da7b40da8fb31d5325f3526ce4f26ad`,
sdist SHA-256
`49b71004a17fc3ff48e1f487b73d5640bdcbca5bc2d5058fe6e6dd660f73669f`.

The hostile-configuration validation revision is the current local pair.
Windows/WSL2 Python 3.13 builds matched byte-for-byte: wheel SHA-256
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`,
sdist SHA-256
`98cb2d399e15e3d90f2f128fa2f4bfd76234ebf0b32edf6877fe2362d6e31575`.

Adding the reusable 100k probe and its small regression test to the sdist
left the wheel byte-identical at
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`.
The current Windows/WSL2 Python 3.13 sdist builds matched at SHA-256
`22fb59f4fc367090a2418e66dbeb044ec40b9133e441f0917af644935bdb4d43`.

After packaging the process-test fixtures with the sdist, Windows and WSL2
Python 3.13 builds again matched byte-for-byte. The wheel remains SHA-256
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`;
the updated sdist is SHA-256
`6804aafa0cb14bc03955b56b173e379689aa188f2deeeb4c909a09f8c298fa4d`.
Both `tests/test_journal_multiprocess_fairness.py` and
`tests/fixtures/journal_fairness_peer.py` are present in the sdist.

The native hostile-JSON boundary revision produced byte-identical Windows
and WSL2 Python 3.13 artifacts: wheel SHA-256
`a5c1523b879d78c5ee38164012a6bd94ef9f5b8289f96e5580f3c8ce4469b96d`
and sdist SHA-256
`a86d04cda36b702259d959270996268989b66faa3852175cee3f005a2d90df8a`.

The Unicode/streaming-bounds revision again matched across Windows and WSL2
Python 3.13: wheel SHA-256
`2ae84d202dd14cc53fcb9acbea8a1c3e0255ff7304a04e02417b48298739e3d5`,
sdist SHA-256
`caea683c135bcbb9f39ede620ac54fd9a1f42844fa13a85332b5aebfd4e94533`.

The Core-owned Pi byte/LF framing revision matched on Windows and WSL2
Python 3.13: wheel SHA-256
`6a0aa4caff004f9d7eda36fb3a4e4f366953f2454bdd38e03b496a5845b69c95`,
sdist SHA-256
`def2ae4bd8a1716fa0447cd2d7c2612e3164bb52fa60a29fc9946433f321a8ad`.

The Pi response-correlation fence revision matched on Windows and WSL2
Python 3.13: wheel SHA-256
`10b5b0385ea0dbface89a88d8c816a87720317797ae0c3b7c1417020de66e7a5`,
sdist SHA-256
`cf392f422a3336682063cd6467b4cc653fc877c733ca99125fe631bd2ea0012f`.

The native-history fairness revision matched on Windows and WSL2 Python
3.13: wheel SHA-256
`ccec3e29b299069d3744ae46995c903097a185aa42f48455bcdaf9340db14b78`,
sdist SHA-256
`9a88d7a90c9873603acb6ebbd45dcdbe5496073c24e7c96036e85f9c250cdb25`.

The Codex slow-subscriber isolation revision matched on Windows and WSL2
Python 3.13: wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`2fbff8ba154c08c068a0585dd9cc5f39d6660590edcb30ad5ccc8c7518b45da6`.

The follow-up scripted stdout-flood and urgent-control test revision also
matched across Windows and WSL2: unchanged wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`8d41b67f41baf8b8a45f28c58a74570e11f8ec84c2fe2701ba5cab78106bb3db`.

The shared-history pressure test revision matched across Windows and WSL2:
unchanged wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`,
sdist SHA-256
`1ad6d9ea0c7aa74e429ed677145f963fda9e6bc6c519d6a770d7cb6cd12620b5`.

The multi-session byte-fairness Core fix matched across Windows and WSL2:
wheel SHA-256
`360b0b02df671230dc4ede62a31b8bd801c36c64b4e3eb3c610320c31b11d562`,
sdist SHA-256
`e60817cec8caf884f1d19e47fce006dc18a343460638598aa1b5b40d1ed758bc`.

The large-incoming-event replay preflight revision matched across Windows
and WSL2: wheel SHA-256
`43c78dfae685052830df647df3b7afdb64d318e322009ee4f0fc79bc6b251915`,
sdist SHA-256
`8378660e9d38e94b8ad19b5df51f443a3895da4de5ffd217d18814884c58d7c9`.

The bounded journal-compaction revision matched on Windows and WSL2:
wheel SHA-256
`6a40a33ee9b2664c609066c80fadc5529da4d5eaf8c34e50589c11b5eeb7f514`,
sdist SHA-256
`e996306abd7da5078e8ce8c2691592638e98e13385a9287d545396efa5896f5d`.

The durable session-claim revision matched across Windows and WSL2:
wheel SHA-256
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`,
sdist SHA-256
`529886b5f79907d746270db8a3e55f10b2665f63944f5b3c81e717345de7fc78`.

The two-process session-claim contention test revision matched across
Windows and WSL2: unchanged wheel SHA-256
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`,
sdist SHA-256
`1b0a6ddedf0893ad5c934da2c8a6b00b7731b100dc61a2df63941314a75584bc`.

The durable session-claim inventory revision matched across Windows and WSL2:
wheel SHA-256
`f2d5a424d72b5e1e553c323ca301eabe7403383afeeb87e4591a757382b1ac67`,
sdist SHA-256
`d23cf8762271c81d087bcb3b1994a2f9e659421ea7f29492cf6bd16febc26dc8`.

The bounded reconcile-request revision matched across Windows and WSL2:
wheel SHA-256
`8eab5d00554a8ae8f8de4b23369ac9eb225abad1666633762a2f9cdb0d63a069`,
sdist SHA-256
`43de0cb26b02f54dcfe44e3f98e319f59f52a439728d87e2a2ea0670c6bdfe87`.

The reusable journal reopen-conformance revision matched across Windows
and WSL2: wheel SHA-256
`c8df78f8165708bc4db717666efaf7f24e1ebbfb6b4b5091368a9096d9eb640b`,
sdist SHA-256
`ec330b7faa08417dd011fe98b057e51c0284c1f0251be965d210662a3b576cee`.

The Core-owned process-birth-record revision matched across Windows and
WSL2: wheel SHA-256
`01b315cf82881f55eb7349511bbe5bedb7a88e41c7fe39b4de6e92672ac26ced`,
sdist SHA-256
`84adc190d7ec6139443ccd8714d08cd22f5bab91bf15560918f6f4cc43e7e255`.

The real-owned-child synthetic factory integration test changed only the
sdist; Windows/WSL2 matched: unchanged wheel SHA-256
`01b315cf82881f55eb7349511bbe5bedb7a88e41c7fe39b4de6e92672ac26ced`,
sdist SHA-256
`a28decaf9eca334f171f9e05b4d13b48009808b01a2b58ffac9a1a89b446ec06`.

The read-only process-birth-observation revision matched across Windows
and WSL2: wheel SHA-256
`63f12188eb648867c33445e5d504ee57db5a60c3d6209837078479d4a0ac0383`,
sdist SHA-256
`d7ffbedf56a1fb13bd03379c733b3a33f8657a8f95d2c157a603a92c1a703cd9`.
