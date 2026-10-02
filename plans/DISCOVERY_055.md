# Overlapping automatic and explicit Pi discovery

Core .54 could list the same Pi Node/CLI installation twice when the managed
PATH layout and an explicit pi_install_root/pi_node configuration overlapped.
Two Windows layout tests reproduced this against the installed .54 package.

Core .55 consolidates identical full observations by physical installation
reference at the public discovery facade boundary. Distinct installations with
identical bytes remain separate. Conflicting evidence for one reference raises
PROFILE_DRIFT; the implementation does not choose an arbitrary version, trust
level or fingerprint. Cooperative cancellation is checked during consolidation.
There is no wire revision/schema change or automatic trust promotion.

Installed Windows Python 3.13.1: 62 passed. Installed WSL Linux Python 3.12.13:
60 passed, two Windows-layout skips. Tests cover duplicate automatic/explicit
layouts, distinct identical-byte targets, conflicting fingerprint/trust/version/
build identity, cancellation, inventory reducers and trust/prepare guards.
JUnit before/after evidence is beside this report. The Windows environment was
newly created with the wheel and pytest; every packaged Python file was compared
with the reviewed source. Complete CI/provider acceptance remains separate.
