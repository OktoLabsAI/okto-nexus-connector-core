# TK-42 partial offline package evidence — 2026-09-26

`tools/verify_offline_artifacts.py` creates separate clean virtual environments
for the local wheel and sdist. It requires a caller-supplied wheelhouse for the
current Python/platform and installs with `pip --no-index`, no build isolation
for the sdist, and no pip cache. The sdist's build backend (`setuptools` and
`wheel`) is installed from the same local wheelhouse. It checks installed
version, Core public API import, bundled schemas/manifest, `py.typed`, pinned
Codex schema and Pi extension resource. The wheel path additionally runs
application-free embedded and remote consumer smokes against its SHA-256.

The wheelhouse was prepared separately with `pip download --only-binary=:all:`;
that preparation used the package index and is not claimed to be offline.
Both artifact installations and checks passed with index/cache access disabled
on the local Windows and Ubuntu WSL2 Python 3.11–3.13 matrix. The sdist build
backend is explicitly reinstalled from the supplied wheelhouse even when a
virtual environment seeded an older copy. Current wheel SHA-256:
`f465c9355d8149b0559c8b3e6ed863bcab4ee44571b2af68e3e83a30a04a463f`;
sdist SHA-256:
`aefa9555bacb8accc9c5094758b4772fe5fa1ee20e49e6550576ed2133a72e6e`.
All six local interpreter/platform combinations built identical distributions. The CI and protected
release workflows now prepare a wheelhouse and run this check in their jobs;
those hosted jobs remain `NOT_RUN`.

This is not the full TK-42 gate: the hosted Windows/Linux matrix,
independent builders, other operating systems and a physically
network-isolated machine remain unverified. The NXL bundle is still
`development-partial`, and real Server/Connector integration is separate.

After the runtime sink update, Python 3.13 Windows artifacts (wheel
`b8d55fb2b2758424ffcb3fc60cec152c8cddc76e86831fde254059716e9f054d`,
sdist `016714d964567e06933b50bcda34114c0d9394192089441c1447142413ed5537`)
passed both offline installs and resource/consumer checks. A final contract
wording correction changed package bytes; the latest Windows/WSL2 matching
artifacts are wheel
`52e51b2299f72693d3f6d3deecb562a8463de11e33dd0a286d247071e5a55a6b`
and sdist
`03428288b96e63876bb3fe37f93a6a5cf27fd5c769462b4f13607530266c178d`.
The latest Windows Python 3.13 wheel and sdist passed the offline checks and
the clean-wheel consumer verifier. The 3.11/3.12 checks have not been rerun
against the changed tree.

The Server/executor quota revision produced the current wheel
`e5f08617c4681edfcdfb79da3b58c30454bf9e90e8c43ff2818cf00b952f4fc0`
and sdist
`025e31e617eb0d56673151bf8bbcc67a25ed1cf6337ab408adcc62dbc11b2511`.
Both passed Windows Python 3.13 offline installation; the clean-wheel
embedded/remote consumer smokes passed. WSL2 built byte-identical artifacts,
but offline installation of this revision was not rerun there.

The latest event-recovery revision produced wheel
`1218812c90bcf97a9a873762ab9d543adea66f04347395419a2a78b0bda051df`
and sdist
`1786329577618aad75f4f7166baba1a86647a211e5619a49f25dc6f2b5fc8f36`.
Both passed Windows Python 3.13 offline installation and resource checks;
the clean-wheel embedded/remote consumer smokes passed. WSL2 Python 3.13
built matching bytes, but offline installation of this revision was not run
there.

The current logical-quota recovery revision has wheel SHA-256
`717b1c63124a49bd8fdca2330f917f279fc15ff5e6ab2550bced13029782bca0`
and sdist SHA-256
`cebf80190e693b5c2f98610023f14db0addf6d867162b27587adb850ac1322ce`.
Both passed Windows Python 3.13 offline installation/resource checks; the
clean-wheel embedded/remote smokes passed. WSL2 produced matching bytes, but
offline installation of this revision was not rerun there.

The current sink-race correction produced wheel SHA-256
`220236571181ebad7327e6c6a93b7b113422e2978d1c6acdfbd2605df4c5d680`
and sdist SHA-256
`a5995c440371a1ae7fa8a0e5e59601d0555a4364e53257d5631428960f49ab2c`.
Both passed Windows Python 3.13 offline installation and resource checks;
the clean-wheel embedded/remote consumer smokes passed. WSL2 built matching
bytes, but this revision's offline installation was not run there.

The current global-operation-counter revision produced wheel SHA-256
`1580cb76787b72516d951a79d3b77b9b9da7b40da8fb31d5325f3526ce4f26ad`
and sdist SHA-256
`49b71004a17fc3ff48e1f487b73d5640bdcbca5bc2d5058fe6e6dd660f73669f`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The current hostile-configuration revision produced wheel SHA-256
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`
and sdist SHA-256
`98cb2d399e15e3d90f2f128fa2f4bfd76234ebf0b32edf6877fe2362d6e31575`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The subsequent reusable-probe revision retained wheel SHA-256
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`
and has sdist SHA-256
`22fb59f4fc367090a2418e66dbeb044ec40b9133e441f0917af644935bdb4d43`.
Both passed Windows Python 3.13 offline installation/resource checks. The
sdist includes `tools/profile_journal_admission.py`; WSL2 built matching
bytes, but offline installation of this revision was not run there.

The process-fairness/fixture-packaging revision retained wheel SHA-256
`f47757aefe1eccdd25d0a01f385e739f991d2d641092ab53641cd594817c6f53`
and produced sdist SHA-256
`6804aafa0cb14bc03955b56b173e379689aa188f2deeeb4c909a09f8c298fa4d`.
Windows Python 3.13 offline wheel/sdist installation and resource checks
passed. Clean-wheel embedded/remote consumer smokes passed. WSL2 built
matching bytes; offline installation of this revision was not run there.

The native hostile-JSON boundary revision produced wheel SHA-256
`a5c1523b879d78c5ee38164012a6bd94ef9f5b8289f96e5580f3c8ce4469b96d`
and sdist SHA-256
`a86d04cda36b702259d959270996268989b66faa3852175cee3f005a2d90df8a`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The Unicode/streaming-bounds revision produced wheel SHA-256
`2ae84d202dd14cc53fcb9acbea8a1c3e0255ff7304a04e02417b48298739e3d5`
and sdist SHA-256
`caea683c135bcbb9f39ede620ac54fd9a1f42844fa13a85332b5aebfd4e94533`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The Pi byte/LF framing revision produced wheel SHA-256
`6a0aa4caff004f9d7eda36fb3a4e4f366953f2454bdd38e03b496a5845b69c95`
and sdist SHA-256
`def2ae4bd8a1716fa0447cd2d7c2612e3164bb52fa60a29fc9946433f321a8ad`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The Pi response-correlation fence revision produced wheel SHA-256
`10b5b0385ea0dbface89a88d8c816a87720317797ae0c3b7c1417020de66e7a5`
and sdist SHA-256
`cf392f422a3336682063cd6467b4cc653fc877c733ca99125fe631bd2ea0012f`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The native-history fairness revision produced wheel SHA-256
`ccec3e29b299069d3744ae46995c903097a185aa42f48455bcdaf9340db14b78`
and sdist SHA-256
`9a88d7a90c9873603acb6ebbd45dcdbe5496073c24e7c96036e85f9c250cdb25`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The Codex slow-subscriber isolation revision produced wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`
and sdist SHA-256
`2fbff8ba154c08c068a0585dd9cc5f39d6660590edcb30ad5ccc8c7518b45da6`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The follow-up native stdout-flood/urgent-control test revision produced
unchanged wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`
and sdist SHA-256
`8d41b67f41baf8b8a45f28c58a74570e11f8ec84c2fe2701ba5cab78106bb3db`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The shared-history pressure test revision produced the same wheel SHA-256
`c3c597c705e01a38338791eefdaa237bd923657dbab14a9de32387179a5b32fd`
and sdist SHA-256
`1ad6d9ea0c7aa74e429ed677145f963fda9e6bc6c519d6a770d7cb6cd12620b5`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The multi-session byte-fairness Core fix produced wheel SHA-256
`360b0b02df671230dc4ede62a31b8bd801c36c64b4e3eb3c610320c31b11d562`
and sdist SHA-256
`e60817cec8caf884f1d19e47fce006dc18a343460638598aa1b5b40d1ed758bc`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The large-incoming-event replay preflight revision produced wheel SHA-256
`43c78dfae685052830df647df3b7afdb64d318e322009ee4f0fc79bc6b251915`
and sdist SHA-256
`8378660e9d38e94b8ad19b5df51f443a3895da4de5ffd217d18814884c58d7c9`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The bounded journal-compaction revision produced wheel SHA-256
`6a40a33ee9b2664c609066c80fadc5529da4d5eaf8c34e50589c11b5eeb7f514`
and sdist SHA-256
`e996306abd7da5078e8ce8c2691592638e98e13385a9287d545396efa5896f5d`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The durable session-claim revision produced wheel SHA-256
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`
and sdist SHA-256
`529886b5f79907d746270db8a3e55f10b2665f63944f5b3c81e717345de7fc78`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The two-process session-claim test revision produced unchanged wheel SHA-256
`eb78979de0848381e4a056faccbed4ddc49f547c5664024047dfc9f208649382`
and sdist SHA-256
`1b0a6ddedf0893ad5c934da2c8a6b00b7731b100dc61a2df63941314a75584bc`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The durable session-claim inventory revision produced wheel SHA-256
`f2d5a424d72b5e1e553c323ca301eabe7403383afeeb87e4591a757382b1ac67`
and sdist SHA-256
`d23cf8762271c81d087bcb3b1994a2f9e659421ea7f29492cf6bd16febc26dc8`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The bounded reconcile-request revision produced wheel SHA-256
`8eab5d00554a8ae8f8de4b23369ac9eb225abad1666633762a2f9cdb0d63a069`
and sdist SHA-256
`43de0cb26b02f54dcfe44e3f98e319f59f52a439728d87e2a2ea0670c6bdfe87`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation of this revision was not run there.

The journal reopen-conformance revision produced wheel SHA-256
`c8df78f8165708bc4db717666efaf7f24e1ebbfb6b4b5091368a9096d9eb640b`
and sdist SHA-256
`ec330b7faa08417dd011fe98b057e51c0284c1f0251be965d210662a3b576cee`.
Both passed Windows Python 3.13 offline installation/resource checks and
clean-wheel embedded/remote consumer smokes. WSL2 built matching bytes;
offline installation was subsequently run on WSL2 and passed on Python
3.11–3.13. The same pair also passed Windows Python 3.11–3.12. The complete
local six-environment record is in `offline-six-env-2026-09-26.md`.

The process-birth-record revision produced wheel SHA-256
`01b315cf82881f55eb7349511bbe5bedb7a88e41c7fe39b4de6e92672ac26ced`
and sdist SHA-256
`84adc190d7ec6139443ccd8714d08cd22f5bab91bf15560918f6f4cc43e7e255`.
Both passed offline installation/resource checks in all six local
Windows/WSL2 × Python 3.11–3.13 combinations and the clean-wheel
embedded/remote consumer smokes. Hosted and real-consumer checks remain open.

The later synthetic factory integration test left the wheel unchanged and
updated the sdist to SHA-256
`a28decaf9eca334f171f9e05b4d13b48009808b01a2b58ffac9a1a89b446ec06`.
The pair repeated and passed the same six local offline installation/resource
checks and clean-wheel embedded/remote consumer smokes.

The process-birth-observation revision produced wheel SHA-256
`63f12188eb648867c33445e5d504ee57db5a60c3d6209837078479d4a0ac0383`
and sdist SHA-256
`d7ffbedf56a1fb13bd03379c733b3a33f8657a8f95d2c157a603a92c1a703cd9`.
Both passed the six local Windows/WSL2 × Python 3.11–3.13 offline
installation/resource checks and clean-wheel consumer smokes.
