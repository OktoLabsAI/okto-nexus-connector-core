# Claude provider environment

When a host approves the current account's default `~/.claude` directory,
Core preserves the account home and leaves `CLAUDE_CONFIG_DIR` unset. It also
preserves `USER` and `LOGNAME`. This allows Claude Code to use its existing
macOS login instead of looking for authentication under a redirected home.

An explicitly configured custom directory remains bound through
`CLAUDE_CONFIG_DIR`. An existing host override is not treated as the default.

Provider authentication and Nexus MCP authentication are independent. The
process-specific MCP configuration and session bearer remain unchanged.

Regression coverage lives in `tests/test_environment.py`. Native Keychain
behavior must additionally be verified on macOS; Windows tests verify the
environment construction, not access to the macOS Keychain.
