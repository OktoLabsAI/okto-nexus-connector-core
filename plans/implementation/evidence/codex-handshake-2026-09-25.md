# K05.1 Codex app-server handshake — 2026-09-25

The [official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server)
specifies a JSONL `initialize` request followed by an `initialized`
notification before other methods. The Core-copied Codex adapter now sends
that notification, uses a neutral `nexus_connector_core` default client
identity, and accepts a validated identity supplied by its trusted host. Its
version observation is scoped to the selected client's user-agent prefix,
not the source Nexus application's prefix.

An explicitly selected native Codex 0.157.0 Windows/x86_64 executable was
surveyed with `tools/probe_codex_handshake.py --adapter-thread-start` in a
disposable `CODEX_HOME`. The transport observed `initialize` response keys
`codexHome`, `platformFamily`, `platformOs`, `userAgent`, and a
`thread/loaded/list` result with `data`, `nextCursor`. The user-agent began
`nexus_connector_core_probe/0.157.0`. The full Core adapter then completed
`initialize` → `initialized` → `thread/start`, obtaining a thread ID and
observing version 0.157.0. The selected executable fingerprint was checked
again after the transport survey. Neither path sent `turn/start` or any model
request; the probe did not supply authentication or issue a model turn.

A strict synthetic peer test rejects `thread/start` unless it first receives
`initialized`; it passes with the adapted Core code. Client identity
validation and user-agent scoping also have a focused test. The local native
observation proves only this no-turn handshake on this one build/platform.
It does not qualify event correlation, notifications during turns, control
commands, model execution, capabilities, other versions, or Linux/macOS.
`QUALIFIED_BUILDS` remains empty and no capability was enabled.
