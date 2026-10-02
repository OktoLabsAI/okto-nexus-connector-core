# Version and platform compatibility

This project is `0.2.52.dev0`, an unpublished development build. Its API and
contract bundle can still change. The current exact revision is
`nxl-1-agent-centric-http-only-2026-09-25-r3` with protocol major `1`.
Negotiation rejects a different major or revision with
`VERSION_INCOMPATIBLE`; there is no implicit r1/r2 upgrade or fallback. The
bundle manifest is marked `development-partial`, so consumers must opt in
explicitly for local checks. No preceding Core release is declared supported;
the current/previous-release TK-44 campaign remains unrun. The manifest's
`core_version` field (currently `0.1.0.dev0`) means "introduced in": the
Core version whose bundle first published this revision — it is NOT the
producing package's version; a stable protocol revision
intentionally keeps the introduced-in value across package releases.

The independent R4 preview uses
`nxl-1-agent-centric-http-only-2026-09-29-r4`. Its manifest is still
`development-partial` and it must not enable production effects. See the
[R4 contract guide](nxl-r4-development.md). Native qualification statements
below describe their recorded historical campaigns; they do not qualify the
current R4 artifact or either application without a new acceptance run.

| Surface | Declared or observed | Qualified for production? |
| --- | --- | --- |
| Python | `>=3.11` package metadata; CI defines 3.11–3.13 on Windows 2022 and Ubuntu 24.04 | No; hosted matrix has not run. Local Windows/WSL2 × Python 3.11–3.13 tests and offline artifact installs are partial evidence. |
| `codex_app_server` managed | Registry lists win32, linux, darwin; selected local Codex 0.157.0 on Windows/x86_64 is **production-qualified** (exact fingerprint `sha256:ed1c7b36…b1f`) for managed conversation, events, steer and interrupt by the recorded real campaigns, and passed the full managed-factory path (prepare → open → real turn → terminal-correlated receipt → bounded shutdown). `item/commandExecution/requestApproval` is qualified (real decline + tardy refusal); other request shapes, `thread/resume`, Linux/macOS and version drift remain unqualified. |
| `pi_rpc` managed | Registry lists win32, linux, darwin; the selected local Pi 0.87.1 Node+CLI pair on Windows/x86_64 is **production-qualified** (composite fingerprint binding both files) for managed conversation, events, queued ID-less steer and abort, and passed the full managed-factory path with a real turn. | No tools/extensions (no real `extension_ui_request` traffic), no automatic-retry semantics, Linux provider behavior, version drift or sustained load; the work bridge stays unqualified. |
| `claude_stream` managed | Registry lists win32, linux, darwin; selected local Claude 2.1.282 on Windows/x86_64 (exact fingerprint `sha256:fc0e3af0…484`) is **production-qualified** for managed conversation, events and interrupt (no steer vocabulary), and passed the full managed-factory path with a real turn. `control_request:can_use_tool/Write` is qualified (forged-kind refusal + real decline); a slow-consumer drain passed; AskUserQuestion/input, Linux/macOS and version drift remain unexercised. |
| `claude_attach` external | Registry lists linux, darwin, freebsd | No; public attach lifecycle and real substrate qualification remain open. |
| Core wheel/sdist | Identical local Windows/WSL2 hashes; isolated offline installs across Python 3.11–3.13 on both local OS environments | Partial packaging evidence only; not hosted CI, native Linux or real consumers. |

Registry platform membership is a code-path gate, **not** a capability grant.
The effective exact-build qualification sets contain exactly the three
Windows builds recorded above (conversation and controls; Claude
interrupt-only). Any drift — version, platform, architecture or file bytes,
and for Pi any change to the bound Node executable or CLI JavaScript —
loses the grant entirely. A version string or synthetic peer does not
qualify a provider. Unsupported adapter/platform selection fails closed.
The immutable NXL schemas and bundled fixtures are Core-owned; application
consumers must pin the same wheel and manifest hash.

Any security-semantic contract change requires version/revision decision,
updated schemas/fixtures and consumer tests. Published compatibility ranges
and real Server/Connector cutover remain future gates. See
[adapter provenance](adapters.md) and the [implementation status](../plans/implementation/status.md).
