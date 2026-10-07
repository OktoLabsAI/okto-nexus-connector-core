# MCP inheritance (Core 0.0.3)

`HarnessSettings.inherit_global_mcps` accepts `enabled` or `disabled` for Codex
and Claude. Hosts resolve inherited policy before constructing the opening.
The setting participates in the profile, R4 opening hash and receipt binding.
Pi rejects it because its Nexus integration is a native tools bridge.

`child_environment` requires a trusted provider directory when enabled. It reads
only global MCP-declared environment references locally, filters privileged names
and values, and returns a protected process environment. It does not serialize
external secrets to the wire, receipts, profiles or argv. The native harness owns
OAuth and configuration precedence; project configuration can also participate.

Managed HTTP tools always carry process-level configuration. Claude drops
`--strict-mcp-config` only when inheritance is enabled. Codex recursively merges
its MCP table, so disabled global names and the injected Nexus entries are sent
in one TOML table. Quoted/dotted entry names must not be encoded as CLI dotted
paths. Project-only servers remain governed by native workspace policy.

The R4 optional field and bundled schema checksum were updated together. Hosts
must upgrade together (Nexus 0.2.2 / Connector 0.0.2). Missing settings preserve
the previous contract. `tests/test_mcp_inheritance_native.py` is opt-in with
`NEXUS_TEST_NATIVE_MCP=1`; it tests an installed Codex in disposable directories,
without sending a model turn. Ordinary composition tests cover both adapters.
