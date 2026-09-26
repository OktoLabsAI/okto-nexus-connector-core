# Direct HTTP configuration and JSON merge — 2026-09-25

K03.5/K09.2 partial evidence on Windows/Python 3.13. `direct_http_config`
now requires a trusted Server origin allowlist and an explicit assertion that
loopback is reachable from the harness process. It rejects HTTP off loopback,
remote loopback, URL userinfo/query/fragment/control characters, malformed
ports and credential-like capability references. It only returns declarative
data; it has no MCP listener, proxy or SDK.

`config_document` provides a pure JSON entry plan and optimistic revision
check. A host supplies the selected document and its previously owned entry;
the planner refuses to replace an entry without that ownership evidence,
preserves unrelated entries structurally, reports changed field names without
rendering values, and detects intervening document edits by SHA-256. Its
replacement bytes are suppressed from object `repr` to reduce accidental
secret disclosure. No file is selected, read or written by this module.

Verification:

- `pytest -q tests/test_harness_config.py tests/test_config_document.py`:
  27 passed.
- `pytest -q`: 183 passed, 66 skipped.
- `python -m build --wheel --sdist`: passed.
- `python tools/verify_wheel.py`: clean wheel installation, imports,
  contract hashes, and no Nexus/Connector imports in packaged Python passed.

SHA-256: wheel
`12bbda299a5e1e640b9eb3a241a7c23b6a0f32e76f95932df676e90fd2c983b2`;
sdist `a3095b87345c656d569fc39b1a89cdccb20c801c2832c0e54251853f9c13453e`.

This does not complete K03.5/K09.2: the host still needs consent, a secure
backup and OS-qualified atomic lock/CAS writer. TOML and native harness-specific
formats, capability injection/renewal and actual host reachability/provider
qualification remain unimplemented or unverified. TK-15/TK-34 and the joint
gates remain NOT_RUN in their full prescribed scope.
