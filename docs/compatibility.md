# Version and platform compatibility

This project is `0.1.0.dev0`, an unpublished development build. Its API and
contract bundle can still change. The current exact revision is
`nxl-1-agent-centric-http-only-2026-09-25-r3` with protocol major `1`.
Negotiation rejects a different major or revision with
`VERSION_INCOMPATIBLE`; there is no implicit r1/r2 upgrade or fallback. The
bundle manifest is marked `development-partial`, so consumers must opt in
explicitly for local checks. No preceding Core release is declared supported;
the current/previous-release TK-44 campaign remains unrun.

| Surface | Declared or observed | Qualified for production? |
| --- | --- | --- |
| Python | `>=3.11` package metadata; CI defines 3.11–3.13 on Windows 2022 and Ubuntu 24.04 | No; hosted matrix has not run. Local Windows/WSL2 × Python 3.11–3.13 tests and offline artifact installs are partial evidence. |
| `codex_app_server` managed | Registry lists win32, linux, darwin; selected local Codex 0.157.0 on Windows/x86_64 completed a no-turn handshake and, under explicit user authorization, a real three-turn campaign: plain turn with `turn/completed` terminal, steer with the expected native turn ID applied mid-turn, and interrupt ending `interrupted`. | No approval/input (HITL) traffic, `thread/resume`, Linux/macOS or version drift exercised; production allowlist stays empty. |
| `pi_rpc` managed | Registry lists win32, linux, darwin; selected local Pi 0.87.1 on Windows/x86_64 completed ID-echo readiness and, under explicit user authorization, real campaigns: one no-tools provider turn, then steer (queued `queue_update`, next-turn-boundary delivery as a user message, settle only at `agent_settled`), abort (settle observed before the ack, matching the documented wire order), follow-up submit after abort, and bounded close during a live turn. Its managed shell launcher can be selected as an explicit Node executable plus installed Pi CLI JavaScript, with both files bound to the candidate fingerprint. | No tools/extensions (no real `extension_ui_request` traffic), no automatic-retry semantics, Linux provider behavior, version drift or sustained load; production allowlist stays empty. |
| `claude_stream` managed | Registry lists win32, linux, darwin; local Claude 2.1.282 observed and, under explicit user authorization, a real stream-json campaign: plain turn with `result:success` terminal after deltas, a second turn over the same process, and an interrupt while generating that produced `control_response:success` and an honest `result:error_during_execution` terminal. | No approval/input or `can_use_tool` traffic, no slow-output drain case, requesting-phase refusal remains synthetic pre-write evidence, Linux/macOS and version drift unexercised; production allowlist stays empty. |
| `claude_attach` external | Registry lists linux, darwin, freebsd | No; public attach lifecycle and real substrate qualification remain open. |
| Core wheel/sdist | Identical local Windows/WSL2 hashes; isolated offline installs across Python 3.11–3.13 on both local OS environments | Partial packaging evidence only; not hosted CI, native Linux or real consumers. |

Registry platform membership is a code-path gate, **not** a capability grant.
The effective exact-build and control qualification sets are empty. Native
eligibility must be established for the selected binary's kind, observed
version, platform, architecture and SHA-256 fingerprint (for Node-launched
Pi, a composite fingerprint of Node and the installed CLI); a version string or
synthetic peer does not qualify a provider. Unsupported adapter/platform
selection fails closed. The immutable NXL schemas and bundled fixtures are
Core-owned; application consumers must pin the same wheel and manifest hash.

Any security-semantic contract change requires version/revision decision,
updated schemas/fixtures and consumer tests. Published compatibility ranges
and real Server/Connector cutover remain future gates. See
[adapter provenance](adapters.md) and the [implementation status](../plans/implementation/status.md).
