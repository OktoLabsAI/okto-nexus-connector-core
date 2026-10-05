# Passive POSIX package discovery — development .56

Known npm Codex symlinks now resolve to their installed native payload in
nested, hoisted or bundled Linux/Darwin layouts. Pi npm symlinks and managed
release launchers resolve to explicit Node/CLI pairs. Unknown launchers remain
visible without interpreting shell or JavaScript. A launcher is superseded only
after its physical payload successfully becomes a candidate. Trust is checked
against that physical target; discovery never executes a provider or grants
runtime authorization.

This fixes a demonstrated POSIX layout limitation, not a confirmed explanation
for the macOS user's zero Codex/Pi candidates in Connector issue #1. Actual Mac
installation paths are still needed. Darwin fixture coverage does not provide
a macOS containment backend or qualify native macOS execution.

## Evidence

- Installed .55 failed 14 of the original 15 POSIX layout cases; see
  `posix-discovery-before.xml`. The final fixture set has 18 cases including
  invalid metadata, absent payloads and non-executable native payloads.
- Official Codex 0.159.0 npm main and Linux x64 packages were downloaded with
  install scripts disabled, extracted into a disposable prefix and discovered
  with process spawning forbidden. .55 selected `bin/codex.js` with unknown
  architecture; .56 selected the x86_64 native payload. Both remained untrusted
  with no observed version. See `posix-discovery-npm-before.json` and
  `posix-discovery-npm-after.json`. This proves discovery, not provider execution.
- Fresh installed Windows Python 3.13.1 suite: 1121 passed, 95 skipped,
  333.17 seconds (`posix-discovery-windows-full.xml`).
- Initial fresh installed WSL Linux Python 3.12.13 suite: 1190 passed,
  24 skipped, 2 failed, 318.77 seconds (`posix-discovery-linux-full.xml`).
  Both failures are retained, not counted as a passing campaign.
- The exact Pi inventory fixture inherited the machine's real PATH Pi.
  The same failure was reproduced against installed .55 in
  `posix-discovery-c2-baseline055.xml`. Its PATH is now fixture-local; exact
  expected versions, ordering and launch scripts remain asserted.
- The idle socket test now observes server-side admission before closing the
  service. A completed client handshake alone could instead race listener
  shutdown and receive a reset. The admitted socket must still produce EOF,
  leave no handlers/writers and cause no backend call. Production socket code
  is unchanged.
- Reviewed installed focused tests: Linux 39 passed/1 skipped and Windows
  22 passed (`posix-discovery-{linux,windows}-reviewed.xml`).
- Reviewed complete Linux campaign: 1192 passed, 24 skipped, 299.22 seconds
  (`posix-discovery-linux-full-reviewed.xml`). Both OS full campaigns retain
  two historical warnings (injected Pi death callback and unawaited slow-close
  test coroutine); these passes do not claim warning-free qualification.

All 96 wheel package files match the reviewed source byte-for-byte. Development
wheel SHA-256: `eb067ffd81085f9394a3bbcb787a660e275b46916c90c8eef8c9bba3083171b4`.
The pre-fixture-review sdist SHA-256 is
`10c9a5bbe03dd7ce03ab93b518285da28a54c0625bd92d8bf81d691098ac1871`;
it is historical and must be rebuilt before final artifact freeze.

After the two fixture corrections, rebuilding produced wheel SHA-256
`7f19885f28b16dbfce66b969ab42c79b9947246416c71147315006b6e618b1f6`
and sdist SHA-256
`b3252f033494550c857a5f9f1dc7da32cc5fa2d29e8f09048ba24f0da6f22804`.
Every wheel member (including metadata/RECORD) has identical bytes to the
installed tested wheel; only the archive representation hash differs.
`tools/verify_wheel.py --artifact-dir <reviewed-dist>` also completed on Windows
Python 3.13.1: a new temporary environment installed the wheel and declared
dependencies, imported resources outside the checkout with `-I`, checked
contracts/journal conformance and passed embedded/remote consumer smokes.
These are Core consumer smokes, not full Nexus/Connector acceptance.

Nexus/Connector adoption, final three-repository artifact freeze, full hosted
matrix and native-provider acceptance remain open. All local Linux evidence
uses WSL on the same computer; independent-machine acceptance remains manual
with the user.
