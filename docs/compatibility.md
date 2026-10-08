# Version and platform compatibility

Current package version: `0.0.9`. Linux guardians persist a private completion
receipt after reaping their entire owned tree. A replacement owner can confirm
containment after abrupt owner death without signalling historical process IDs.
Missing, incomplete or untrusted receipts remain unknown, including externally
killed guardians. Receipt files must remain available across owner restarts.

Historical owned-slot release also reconciles openings interrupted before their
success receipt committed. Matching binding, claim, original operation and
released slot remain mandatory. Intermediate/unknown operation outcomes are not
rewritten as success and never authorize replay.

When productive journal admission is full, submit and steer raise
`OperationNotAdmitted` with a correlated no-effect refusal. This is not a durable
Core receipt: the host must persist the refusal in its publication obligation
before publishing it. Refusals leave interrupt/close capacity intact. The host
retains replay identity while the healthy native session stays available after
capacity returns. A crash before host persistence requires ordinary reconciliation.

Codex initialization failures preserve observed
process containment, allowing a terminal startup failure without indefinite
recovery. A later startup attempt cannot inherit the earlier containment proof.

Native turn-start events retain their phase
and current operation identity; foreign or idle starts are refused.

Pi native tools include agent list/get,
capability discovery and workspace-bound coordination health. Their socket
requests retain session identity, action ceilings and lease checks; Nexus
enforces the agent's current domain permissions and communication visibility.

Pi startup failures retain process ownership
and report confirmed containment, allowing a terminal protocol failure instead
of unnecessary recovery. Unknown containment remains unknown.

Claude result-only responses retain their final
text, and stale native decisions have durable no-effect refusals. This release
retains optional global MCP configuration
inheritance with scoped credentials, alongside the runtime recovery fixes from
`0.0.2`. It fixes Codex/Pi process identity capture,
persists Windows Job container identities for recovery after owner failure, and
adds opt-in continuous reconciliation after the initial retry budget. Legacy
records without container identities still require independently verified stop.
Protocol revisions remain unchanged.

From `0.2.61.dev0`, managed opening checks the authorized workspace's resolved
path and filesystem identity instead of its mutable directory size and mtime.
Creating, renaming, or removing child files during another session's opening
is allowed. Replacing the root, redirecting its link, or changing launch
artifacts still fails with `PROFILE_DRIFT`. The artifact revalidation frontiers
are unchanged; these checks do not provide an atomic filesystem snapshot.

The first release is `0.0.1`, renumbered from the pre-release development
series. Consumers must pin this release explicitly; it sorts below the old
`0.2.x.dev0` builds. This version reset does not change protocol revisions.
The historical R3 revision is
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

The independent executable R4 contract uses
`nxl-1-agent-centric-http-only-2026-09-29-r4`. Its manifest is `executable`
after installed Core and consumer conformance. Hosts verify it through
`verify_r4_bundle` and negotiate `R4_CONTRACT_REVISION`; historical R3 constants
and resources remain unchanged. Contract promotion does not qualify providers
or bypass host admission and authority checks. See the
[R4 contract guide](nxl-r4-development.md). Native qualification statements
below describe their recorded historical campaigns; they do not qualify the
current R4 artifact or either application without a new acceptance run.

| Surface | Declared or observed | Qualified for production? |
| --- | --- | --- |
| Python | `>=3.11` package metadata; CI runs 3.11–3.13 on Windows 2022 and Ubuntu 24.04 | No production qualification. At `beed295`, all six hosted cells reached tests: each Windows cell had 1120 passes/77 skips, each Linux cell 1174 passes/23 skips. Each also failed the same stale documentation-version assertion, so build/install steps did not run. |
| `codex_app_server` managed | Registry lists win32, linux, darwin; selected local Codex 0.157.0 on Windows/x86_64 is **production-qualified** (exact fingerprint `sha256:ed1c7b36…b1f`) for managed conversation, events, steer and interrupt by the recorded real campaigns, and passed the full managed-factory path (prepare → open → real turn → terminal-correlated receipt → bounded shutdown). `item/commandExecution/requestApproval` is qualified (real decline + tardy refusal); other request shapes, `thread/resume`, Linux/macOS and version drift remain unqualified. |
| `pi_rpc` managed | Registry lists win32, linux, darwin; the selected local Pi 0.87.1 Node+CLI pair on Windows/x86_64 is **production-qualified** (composite fingerprint binding both files) for managed conversation, events, queued ID-less steer and abort, and passed the full managed-factory path with a real turn. | No tools/extensions (no real `extension_ui_request` traffic), no automatic-retry semantics, Linux provider behavior, version drift or sustained load; the work bridge stays unqualified. |
| `claude_stream` managed | Registry lists win32, linux, darwin; selected local Claude 2.1.282 on Windows/x86_64 (exact fingerprint `sha256:fc0e3af0…484`) is **production-qualified** for managed conversation, events and interrupt (no steer vocabulary), and passed the full managed-factory path with a real turn. `control_request:can_use_tool/Write` is qualified (forged-kind refusal + real decline); a slow-consumer drain passed; AskUserQuestion/input, Linux/macOS and version drift remain unexercised. |
| Core wheel/sdist | Identical local Windows/WSL2 hashes; isolated offline installs across Python 3.11–3.13 on both local OS environments | Partial packaging evidence only; not hosted CI, native Linux or real consumers. |

Passive discovery also resolves known POSIX npm Codex symlinks to fixed native
Linux/macOS package payloads, and Pi npm/managed layouts to explicit Node+CLI
pairs. It reads package metadata and files only. Trust applies to the physical
targets, not to the directory containing a launcher. Unknown scripts are not
interpreted; an unresolved script remains an unprobed observation.

macOS process ownership is implemented through a per-launch launchd guardian
job whose coalition pair (resource and jetsam ids, private 40-byte ABI) is the
tree key: membership survives `setsid`/double-fork escapes, signalling is
guarded by birth + coalition revalidation with a `SIGSTOP` interlock and
post-signal birth verification, and stop proof requires two consecutive
complete empty censuses plus a kqueue-confirmed owner-death channel. This is
qualified natively only on the recorded Intel host (macOS 26.4.1, GUI login
session, Python 3.12.4) with synthetic fixtures through the production
backend ([native acceptance campaign](../plans/implementation/evidence/macos-native-acceptance-20261002.md));
real providers, headless/SSH sessions (user-domain bootstrap was refused
natively), Apple Silicon, other macOS versions and hosted CI remain
unqualified, and passive preflight exposes the GUI-session requirement
through its `session_domain` check instead of claiming headless support.

Registry platform membership is a code-path gate, **not** a capability grant.
The conversation qualification set also includes the exact Windows Codex
0.159.0 build recorded in the [September 30 campaign](../plans/implementation/evidence/codex-0159-qualification.md),
in addition to the three historical builds above. Qualification remains scoped
per operation (Claude has interrupt but no steer vocabulary). Any drift —
version, platform, architecture or file bytes,
and for Pi any change to the bound Node executable or CLI JavaScript —
loses the grant entirely. A version string or synthetic peer does not
qualify a provider. Unsupported adapter/platform selection fails closed.
The immutable NXL schemas and bundled fixtures are Core-owned; application
consumers must pin the same wheel and manifest hash.

Any security-semantic contract change requires version/revision decision,
updated schemas/fixtures and consumer tests. Published compatibility ranges
and real Server/Connector cutover remain future gates. See
[adapter provenance](adapters.md) and the [implementation status](../plans/implementation/status.md).
