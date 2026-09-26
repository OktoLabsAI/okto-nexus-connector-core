# K05.1 Codex 0.157.0 protocol schema — 2026-09-25

The [official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server)
says `generate-json-schema` emits a version-specific bundle. The explicitly
selected native Windows/x86_64 Codex 0.157.0 executable (SHA-256
`ed1c7b36e44536809c868864c833af8a857f56599a7a7fe23b908a1ba1093b1f`)
generated the v2 bundle without `--experimental`. Its 618,802-byte output
has SHA-256 `2719fccd25a97a7ce355497ca5e9123a63f6dce7f9f83724a5b73fd927811f59`.
That exact generated artifact was copied into the Core at
`src/nexus_connector_core/native/codex_app_server_0_157_0.schemas.json`;
it is not loaded from the sibling Nexus project or a developer's temp path.

The bundle is included in both wheel and sdist. The clean-wheel verifier
checks its presence and hash from an isolated installation. Focused tests
validate the Core adapter's actual `thread/start` and `turn/start` parameters,
plus started/completed notification fixtures, against the pinned Draft 7
definitions. Generated required fields include `input` and `threadId` for
`turn/start`, `expectedTurnId`, `input`, `threadId` for `turn/steer`, and
`threadId`, `turnId` for `turn/interrupt`.

This is a schema snapshot and a narrow shape test, **not** a complete
qualification. The exact binary/protocol pair still needs real turn,
notification, control, approval, error and lifecycle campaigns before any
native capability may be enabled. Other versions and platforms have no
schema entry; the effective qualified-build set remains empty.
