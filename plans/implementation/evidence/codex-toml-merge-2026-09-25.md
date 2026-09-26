# K03.5/K09.2 Codex TOML planning — 2026-09-25

`config_document.py` now owns pure add/update/removal planning for one
direct-HTTP Codex `[mcp_servers.<name>]` table. Existing entries require an
exact host-supplied predecessor; the parsed TOML tree is checked before and
after editing so third-party entries cannot be silently changed. Only simple
owned tables are replaced or removed; comments, nested tables, inline-table
forms and ambiguous syntax in the owned span fail closed. New entries append
without rewriting existing bytes. A SHA-256 CAS binds each plan to the source
document.

`config_persistence.py` applies the plan under the same adjacent cooperative
lock, reread/CAS, backup and atomic-replace path as JSON. The host selects the
path and approves ownership; a remote request never selects a file. A
non-cooperating writer can still race the final replace, and Windows backup
ACL review remains the trusted host's responsibility.

Focused tests cover third-party preservation, exact ownership, no-op,
removal, malformed/complex TOML refusal, stale plans and file backup/CAS.
Clean-wheel verification exercises the new Core-owned planner. Native Codex
format and provider execution remain unqualified; no global user config was
changed by these tests.

Final local development artifact SHA-256 values: wheel
`1f957c370633fe5fbd7b97a210fcced6084e16044d6ff3e39a4123fb10e45bf0`;
sdist `4a82aece9eac1849bde64f5cda92310779e7f96dc1db84f0400e3f02a24abbc1`.
