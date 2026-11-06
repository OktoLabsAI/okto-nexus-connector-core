# External participant configuration

`nexus_connector_core.participant_config` describes external MCP clients. It is
separate from `HarnessHTTPTemplate`: a participant uses an existing agent key;
managed execution continues to require a scoped `mcp-cap:` reference and the
host's native format qualification. Neither contract grants new authority.

`participant_client_config(...)` creates an immutable `ParticipantClientConfig`.
It records client/version, format/revision, approved origin and `/mcp` endpoint,
entry name, environment reference and selected file scope. Versions describe
the client's observed build; constructing a value does not qualify that build.
An unobserved client build is `None`, never a guessed version or qualification.
The module performs no filesystem, credential, network or process operations.
Pi has no participant HTTP renderer; use its existing supported integration.

| Client | Format | Credential reference |
| --- | --- | --- |
| `claude` | `claude-mcp-json`, `mcpServers` | `headers.Authorization` with a Bearer environment placeholder |
| `codex` | `codex-config-toml`, `mcp_servers` | `bearer_token_env_var` |
| `generic` | `manual-http-json` | Explicit manual instruction; no client installation claim |

The selected variable must use the dedicated `NEXUS_PARTICIPANT_TOKEN_` prefix.
No API key, capability, vault secret, runtime grant, executable or host path is
accepted as a credential reference. The host must authenticate the existing
identity, provide the secret to the actual client process using its approved
credential mechanism, and verify that context separately. A rendered reference
does not establish that an already-running GUI inherited the variable.

HTTPS and exact approved origins are required by default. Loopback use requires
an explicit host reachability assertion. Plaintext remote HTTP requires an
explicit transport-policy assertion; the library does not change Server policy.
Client HTTP redirect behavior requires separate host/client qualification.

`export_participant_config` renders a reference-only fragment. Generic output
is marked `manual_configuration_required`. `plan_participant_config` accepts
the original selected file bytes and returns the existing JSON/TOML plan type,
including source hash and changed fields. The host retains that exact plan
until approval and uses `apply_json_plan_file` or `apply_toml_plan_file` for
the existing bounded, locked, backup/CAS and atomic replacement behavior.

An existing entry requires its exact predecessor from trusted ownership state;
its name or similarity is insufficient. JSON preserves unrelated values (not
formatting); TOML preserves unrelated bytes/comments and newline conventions.
Ambiguous or customized owned TOML is refused instead of silently deleting
comments. Invalid/duplicate inputs fail closed. `plan_participant_removal`
removes only a still-owned entry; it never restores a whole stale backup over
later user edits. Host-side interruption recovery and protection of backups
remain explicit obligations: an old file can contain third-party secrets.
The host can pass `prepare_file(path, kind)` to either persistence helper.
It runs on each empty file before any source/replacement bytes are written;
`kind` is `backup` or `replacement`. The host can restrict a backup ACL and
preserve the selected file's access policy. Failure aborts before replacement.
Without this callback Windows files inherit the parent ACL, which the host
must verify. The callback does not add I/O to the pure renderer or import path.

Official format references checked on 2026-11-05:
[Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
and [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp).
These document the renderer shapes; real binary campaign evidence belongs to
the consuming host's ledger. No model call is needed to validate a config shape.
