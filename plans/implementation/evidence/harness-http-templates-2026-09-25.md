# Harness direct-HTTP templates — 2026-09-25

`harness_http_template` now emits declarative native MCP HTTP client entries
for a trusted host-selected, format-qualified Codex app-server or Claude
stream build. It reuses explicit origin/reachability validation, derives a
stable `NEXUS_MCP_TOKEN_<digest>` environment-variable name from an opaque
local capability ref, and returns a separate name-to-ref binding for the
trusted host's secret resolver. No token value, stdio command, MCP helper,
proxy or server is emitted. Pi and unqualified formats fail closed.

The Codex entry uses `url` and `bearer_token_env_var`, with a standalone
parseable TOML fragment. This follows the
[official OpenAI Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
The Claude JSON entry uses `type: http`, `url`, and an `Authorization` header
referencing `${VAR}`; [Claude Code's MCP reference](https://code.claude.com/docs/en/mcp)
documents both the required type and environment expansion in headers.
The existing Core JSON planner can merge that entry without replacing a
third-party server.

Verification on Windows/Python 3.13:

- Focused harness-config tests: 32 passed. They check no literal token,
  format gating, deterministic ref name, parseable Codex TOML and Claude
  structural merge preserving third-party entries.
- Full `pytest -q`: 231 passed, 66 skipped.
- `python -m build --wheel --sdist` and `python tools/verify_wheel.py`:
  passed with clean wheel installation/import.
- Wheel SHA-256: `6c437cdcd6e8cd474f0a640637666859869f155fbf0ae05a52cedc7e3bb74918`.
- Sdist SHA-256: `a0dda5037edbbd91578e0e227f9709f8a344d4685517b55c9b7c091061064169`.

No real Codex or Claude MCP connection was attempted. This is format-level
unit evidence, not build/provider qualification or the full K09 gate. The
trusted host still must supply the token in the selected process environment,
verify native support, renew/revoke the capability, and apply any persistent
configuration with ownership and consent. The subsequent Core-owned,
ownership-checked TOML planner is recorded in
`codex-toml-merge-2026-09-25.md`; the counts and artifact hashes above are
historical evidence for the earlier template-only build.
