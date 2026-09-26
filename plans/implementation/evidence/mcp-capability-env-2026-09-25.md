# Local MCP capability environment path — 2026-09-25

The native HTTP template now requires an opaque local `mcp-cap:` reference,
separate from provider or canonical-agent credential namespaces. The Core
launch profile must list that reference in `PreparedLaunch.secret_refs`.
`child_environment` accepts a template only for the same adapter, checks
that the environment-variable name is exactly derived from the approved ref,
resolves its value through the injected local `SecretResolver`, and rejects
missing/empty values before spawn. Public overrides still cannot set any
`NEXUS_*` name. Resolver diagnostics are suppressed from the public error.

The copied adapter's private environment seam admits only the narrowly
formatted `NEXUS_MCP_TOKEN_<16 hex>` variable; it continues to reject other
`NEXUS_*` values and known canonical key prefixes. Before constructing the
adapter, `CopiedAdapterFactory` independently checks the variable name
against the `mcp-cap:` refs on the prepared launch. A synthetic factory test
proves the approved value reaches the adapter environment while an operator
key or wrong-ref variable is rejected before adapter construction. No real
provider process was started and no real secret was resolved.

Verification on Windows/Python 3.13:

- Focused environment/template/bridge tests: 44 passed.
- Full `pytest -q`: 235 passed, 66 skipped.
- `python -m build --wheel --sdist` and `python tools/verify_wheel.py`:
  passed with clean wheel installation/import.
- Wheel SHA-256: `a9b769beb9101029dc286ebf7735fa22f29420064c589babfdff2702c0b0b36b`.
- Sdist SHA-256: `2f4e3d1022562506a3d0594f7426f371ffc1845fc335b9f93cb88bc22d068b0e`.

Capability issuance, expiry/rotation, Server-side authorization and real
client connection remain separate unverified gates.
