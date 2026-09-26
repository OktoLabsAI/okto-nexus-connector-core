# Real control/HITL/slow-drain campaigns closing TK-22/23/27/29 — 2026-09-26

User-authorized continuation of the real Windows/x86_64 campaigns against
the production-qualified builds. All probes log protocol metadata only —
never prompt output, model text, stderr or secrets.

**TK-22 — Codex concurrent controls** (`tools/probe_codex_concurrency.py`):
one app-server connector multiplexing two threads. Concurrent `turn/start`s
were accepted with no send errors; both native turn IDs were observed live
at the same time; a steer naming thread A's exact expected turn ID was
applied mid-turn; a steer naming a **stale** turn ID was refused before any
wire write (`STALE_TURN`); an interrupt targeted thread B only — thread A
completed (`completed`) while thread B ended `interrupted`, proving no
cross-turn damage. Close bounded in 0.063 s.

**TK-23 — Codex HITL** (`tools/probe_codex_hitl.py`, opt-in native
approvals): a shell-command prompt produced a real
`item/commandExecution/requestApproval` (availableDecisions `accept`,
`acceptWithExecpolicyAmendment`, `cancel`). The host decline was delivered
through the adapter's checked reply path — mapped to the native `cancel`
decision, never an execpolicy amendment — the request resolved
(`serverRequest/resolved`), and the turn completed. A **tardy** retry of
the same reply after the turn ended was refused. Input elicitation
(`item/tool/requestUserInput`) was not exercised against the real provider;
its denied/tardy paths remain covered by the contained-peer suite, so this
row closes on combined real-approval plus synthetic-input evidence.

**TK-27 — Claude slow consumer** (`tools/probe_claude_slowdrain.py`): a
long streamed turn consumed with a deliberate 25 ms sleep per event while
the adapter's reader drained the child continuously. The `result:success`
terminal was still observed, was the last native event, and no category was
lost. Multi-turn/deltas/system/result against the real provider come from
the 2026-09-26 stream campaign, so this row closes on combined evidence.

**TK-29 — Claude HITL** (`tools/probe_claude_hitl.py`, opt-in native
approvals): a Write-tool prompt produced a real
`control_request:can_use_tool` for `Write`. A **forged tool kind** was
refused before any wire write; the decline was delivered through the
checked reply path and the turn completed with `result:success`. The
error path (`result:error_during_execution` after interrupt) is the
2026-09-26 campaign. AskUserQuestion input remains unexercised on this
build (covered synthetically), so this row also closes on combined
evidence. Bash was auto-allowed by the host's own Claude settings and is
not claimed.

Capability advertisement now matches exactly what was exercised:
`CODEX_NATIVE_REQUEST_CONTRACTS["0.157.0"]` carries only
`item/commandExecution/requestApproval` and
`CLAUDE_NATIVE_REQUEST_CONTRACTS["2.1.282"]` only
`control_request:can_use_tool/Write`; the version observations surface
them as `compatible_native_requests`, so `qualified_capabilities` advertises
approvals for exactly these qualified builds. A focused test pins both the
contracts and the derived capabilities (Claude steer timing stays `None`).

Scope limits: Windows/x86_64, one build per adapter, single host, no
elicitation/input real traffic, no sustained multi-session load.
Verification (all local, `rtk`-prefixed): full Python 3.13 suites passed
Windows 609/73 and WSL2 668/14 (passed/skipped), each with the known
injected legacy Pi warning; the focused allowlist/contract tests pass.
Normalized builds are byte-identical across Windows/WSL2: wheel SHA-256
`bc6b993de05b68dd9eb3a5d58b0655797ed15d10b843f29c7f1c264c16bb273c`, sdist
SHA-256
`6168475fb2e9b838b26902495dc440613813c5aab6a678c92f5e849c1c7bd0a8`.
Strict Twine, development release validation (`publishable:false`) and
offline wheel/sdist installs with both consumer smoke roles passed on
Windows and WSL2 Python 3.13.
