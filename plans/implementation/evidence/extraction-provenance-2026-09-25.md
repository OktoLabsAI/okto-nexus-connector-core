# K00 extraction provenance — 2026-09-25

Read-only baseline: `D:\projetos\Techridy\okto_labs_okto_nexus`, branch
`feature/v0.2.0`, commit `7ed52c22865a92c3768bc32508ed9e35dc5efdc3`.
The only dirty source paths were unrelated HTTP static assets and
`.nexus-policy-guardrail-test/`; none occur below. SHA-256 values are of the
actual source worktree files at this commit and the current Core files, not
an assertion that adapted copies are byte-identical. Source files remain in
Nexus, but the Core runtime imports its **own** copies only.

Source prefix `src/okto_nexus/adapters/outbound/harness/`; destination prefix
`src/nexus_connector_core/`:

| Source | Source SHA-256 | Core destination | Core SHA-256 | Treatment |
|---|---|---|---|---|
| `codex.py` | `1b454623159e1b6af87e82650ee3021bee4d387de9dc9a40b4f993ae57cfe7e8` | `native/adapters/codex.py` | `e1b3d5f88494155339e4da72c1c9937050fcbd94b81ce87af25d38e562d8cd5f` | Copied/adapted |
| `pi.py` | `71a4145c012d0d635f463960e4c8c6cb041b6f3c7da41c0c3b80adbe076213cb` | `native/adapters/pi.py` | `b10fbabf1ea4fafb575ca09c7722fddd12d8dd56a507bb57c4d96ee0e7e5a064` | Copied/adapted |
| `claude_code_stream.py` | `8337c0a510d77825ccb12c19501b9bd6baa5114f6c1c93b22bc71558d548325f` | `native/adapters/claude_code_stream.py` | `3aba184b9dc43b1f325dffb425dbbd8ca5df9df40ffcc328d528b6c6679e5d94` | Copied/adapted |
| `claude_code_attach.py` | `c2c91acf283aa36b85a3e7d3e9521e64e67ec19f209ca6aed23b8a3dca486a19` | `native/adapters/claude_code_attach.py` | `9bd3e2a083b291f445670967c76e90aa296eca7b6620ced64cfe698c863531fe` | Copied/adapted; POSIX not locally qualified |
| `compatibility.py` | `60297af85b907e0fc8d62f9d7b62d647f4b439104ddd2a424ac3bb4ca74c6901` | `native/adapters/compatibility.py` | `7ffb21593ed22327f2ce2493d10eb2135b81344db1f68f9f509f3fc245597dc6` | Copied/adapted; Core qualification reset |
| `environment.py` | `e4fa1d9ed3ae1cce1e70796fc4407037894c0493f05bfbbdc77a4ebea292169f` | `native/legacy_environment.py` | `744773e9d040f93cec0444c45916c7cdb9a3997a057f927c92aee2617e17d85f` | Replaced by restricted local environment seam |
| `framing.py` | `6952bff82203a1977f6c64391482e1509093fa3033ff25042e5e9afc7bed84fc` | `native/framing.py` | `6952bff82203a1977f6c64391482e1509093fa3033ff25042e5e9afc7bed84fc` | Byte-identical copy |
| `event_buffers.py` | `5be20637356c75591acbab6b72182091fdc82624a5d2a197e7419349f1135970` | `native/event_buffers.py` | `5be20637356c75591acbab6b72182091fdc82624a5d2a197e7419349f1135970` | Byte-identical copy |
| `owned_process.py` | `d3b407561bf73f9401aba61da8b5dedf4b1b7b5f978bb3d860aea5be0bf71e99` | `native/process/__init__.py` | `1bdf151ce0985f4121d859e5ee0d7eba5a324022b6b7a43aeb9de98fababfca3` | Copied/adapted and split into platform backends |
| `windows_process.py` | `df657162b31f6f3fa91816a469d608d8d9b4eeba1f81653f4e435d0b8134477a` | `native/process/windows_process.py` | `df657162b31f6f3fa91816a469d608d8d9b4eeba1f81653f4e435d0b8134477a` | Byte-identical copy |
| `linux_process.py` | `2a849c809f47399521dbf3555de8894ac8efd5198370c927d1d54bf0c3368ef5` | `native/process/linux_process.py` | `2a849c809f47399521dbf3555de8894ac8efd5198370c927d1d54bf0c3368ef5` | Byte-identical copy |
| `linux_process_guardian.py` | `b67a6986cd9968837438f8bdc29e3ca6a79481587fe5330cf51cb3f12fcce553` | `native/process/linux_process_guardian.py` | `b67a6986cd9968837438f8bdc29e3ca6a79481587fe5330cf51cb3f12fcce553` | Byte-identical copy |

Additional source files inventoried but **not copied wholesale** into Core:

| Source | SHA-256 | Boundary |
|---|---|---|
| `harness/qualified.py` | `9b9f04f0c2c8c367773dd17df6e6a15bcc64327cc7e0e74a2a535756bbb0dd50` | Nexus-specific qualification; Core starts with empty exact-build allowlist |
| `harness/event_journal.py` | `f3ecfb5e4ad9a90286fd3537e0f25b0b1212c9c30224d2474e7d4251ee4f853d` | Legacy fsynced ingress-segment journal not copied; Core's technical SQLite journal is a different implementation, with parity fault tests still pending |
| `harness/envelope.py` | `096729db06d3a4eb80d4a4a876ca871a5ea59498e99622666df0770ac628fbc8` | Replaced by Core-owned NXL models/schema/codec |
| `harness/secret_redaction.py` | `8b73e96017499fdf47d7b92d9fd0ac8fd40fa18243de7e3e4abbe9cea93f2d37` | Core-owned adaptation at `native/redaction.py` (SHA-256 `98983920e3361d61f304d4af5a2072dc2da091e7bdbe1d1f5518f0c5d6d641d7`); connection-scoped ingress redaction, not a runtime import from Nexus |
| `harness/subscribers.py` | `39f02124e5f5bf5fd37926b1574d158b299a9978a3af29dadaff6f95e9e9a4` | Not copied; bounded Core event buffers/runtime replace parts of it |
| `src/okto_nexus/domain/harness.py` | `4d2f1a1518f2e2b61fc8c4fd4f63f60d7760cef5a48077fc42587d23fc02bb06` | Application domain not migrated |
| `src/okto_nexus/application/harness_supervisor.py` | `b1a5b266fbe89ff663afee942b5c129663164099233447a2adfa9b0cfa64e01e` | Application supervisor not copied wholesale; Core has host-neutral runtime |
| `src/okto_nexus/application/ports.py` | `271754d8d25efee847627085e9ddc2b97af153098245d8bba531810982174ca6` | Application ports not migrated; Core owns neutral ports |

Legacy connector test sources `test_harness_codex_connector.py`,
`test_harness_pi_connector.py`, `test_harness_claude_code_connector.py`, and
`test_claude_code_attach_connector.py` were adapted into the four
`tests/legacy/test_*_legacy.py` suites. Application tests for the supervisor,
routes, tools, persistence and provider campaigns remain in Nexus and are not
evidence of Core or Connector qualification. On Windows, the adapted POSIX
attach suite is skipped; provider-facing suites remain unqualified.

The source `LICENSE` SHA-256 is
`771a71811da3fa1ac46a8cc78121ed5f02f3702bc6c5d59c14210c1638e84c13`;
Core `LICENSE` is
`93f6a543e6e732e00cc1bfa9df213fea1c3df06a2909324c15d3bd73ff2d7efe`.
Their text compares equal after CRLF→LF normalization; byte difference is
line endings. Legal/release review of the custom addendum remains required.

Nexus declares `mcp>=1,<2` and `pydantic>=2` plus HTTP/dashboard/embedding
extras. Core declares only `rfc8785==0.1.4` and `jsonschema==4.26.0` at
runtime, with `pytest`/`build` as test extras. `tools/verify_wheel.py` scans
every wheel Python import and rejects both application imports and any
external import outside those two declared runtime packages. The clean-wheel
installation check passes; a full transitive-license/SBOM review remains K11.

The audit also rejects dynamic imports outside Core's fixed relative adapter
registry, common import-path mutator calls, and file-based module loading. Current Core
package source contains no `okto_nexus` or sibling-project path references;
historical source provenance remains documented here only.

Verification after adding the import boundary audit: `pytest -q` reported
`259 passed, 66 skipped`; the clean-wheel verifier passed on the previously
built wheel. This turn changed no package source, so a wheel rebuild was not
needed for the audit script/evidence changes.
