# Codex 0.159.0-alpha.12.1 Windows qualification

The operator requested completion of the selected Codex runtime configuration.
On 2026-10-03, tools/probe_codex_turn.py exercised the installed Windows x86_64
Codex executable in a disposable workspace using the existing approved login.
The source campaign observed the full prerelease version, completed an ordinary
turn, completed a turn after targeted steer, and completed targeted interruption
with status `interrupted`. Close returned in 0.108 seconds.

The exact executable fingerprint is
`sha256:1722907aa64401bcc9b34467ef5c2af43f6aef9a5045ef04d11d19dfae4589fb`.
The portable build identity is
`sha256:ae7e2bc6f390e2c8bb2258d0665c7c02e189bc2b414283b1e588a56ef20621a6`.

Qualification covers conversation, steer, and interrupt only. It does not
qualify native approvals, authorize local connections, or confer qualification
on the stable 0.159.0 build or other prereleases. Version parsing now preserves
prerelease and build identifiers consistently in the CLI and initialize paths.
Raw protocol metadata is recorded in codex-alpha-20261003.json.
