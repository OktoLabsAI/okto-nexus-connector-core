# Core native approval/input decision seam — 2026-09-26

`NativeApprovalOperation` and `RuntimeCore.decide_native_approval` provide a
host-authorized, journaled response to one pending native Codex or Claude
request. The host must supply a scoped `ExecutionContext` with
`approval.decide` or `input.provide`; the active binding must allow the same
action and have a live lease. Requests are bounded and matched by native ID,
method, request hash and active turn/generation in the copied adapter. The
Core journal records intent and possible effect before the native reply.
`SUBMITTED` means the reply write returned, not that the provider acted.
Stale pre-write refusal becomes durable safe failure; an uncertain write
remains `OUTCOME_UNKNOWN`.

The Core now also indexes each native request only after its event is committed
to the technical journal. A decision must match the committed request's ID,
method, hash, parameters and local generation exactly; otherwise it is
rejected before operation admission. Successful or uncertain replies consume
this process-local pending entry, and terminal turn events invalidate it.
The adapter remains the final live-request fence. The index is not a durable
host-side CAS or reconnect mechanism: Core process ownership is not resumed
after restart.

The public decision path preflights JSON structure and size before
canonicalization/copy. A 64-level ceiling and bounded node/string accounting
reject grossly oversized, cyclic, deeply nested and non-JSON host input before
journal admission; the exact canonical byte ceiling remains 16 KiB. This
closes an allocation/CPU exposure in the otherwise size-limited seam.

Only a SHA-256 digest of the operator response enters the semantic journal
intent. The response itself is validated, size-limited and copied in memory
before the write. The copied Codex and Claude adapters use their original
pending request to determine reply shape and reject caller-edited method or
tool identity. `CopiedAdapterFactory(native_approvals_enabled=True)` is an
explicit opt-in, off by default, and requires both decision actions in the
host-issued launch context. It still requires a qualified native build.

Synthetic runtime tests cover authorization, dedupe, response confidentiality,
unobserved/edited requests, terminal invalidation, stale refusal and uncertain
write. Direct adapter tests cover method/tool
spoofing. A contained Codex JSON-RPC peer sends a native command-approval or
user-input request, waits for the Core response, then completes; tests verify
the event was durable before the host decision, only one correlated reply is
sent, and a late answer is refused. The runtime/bridge/docs focused suite
passed 88 tests in each local Windows/WSL2 × Python 3.11–3.13 environment.

Full Python 3.13 suites passed Windows 583/73 and WSL2 642/14
(passed/skipped), each with one expected legacy injected-thread warning.
The normalized Windows and Linux wheel SHA-256 is
`6d2ba018bcd6dd0d68ccbfca951f0ecd27cf8be10b192384c5f5a9b66cac28c4`;
the matching sdist SHA-256 is
`810cd920e4939703fad079f65867aaa386f2bb35c184688afe5d3b66c1850d91`.
Strict Twine and clean-wheel consumer checks passed. Offline wheel and sdist
installation with resources passed on Windows and WSL2 at Python 3.11,
3.12 and 3.13. Development release validation reports
`publishable: false`.

After the durable-request fence, the focused runtime/bridge/docs suite passed
89 tests in each local Windows/WSL2 × Python 3.11–3.13 environment. Full
Python 3.13 suites passed Windows 584/73 and WSL2 643/14 (passed/skipped),
with the same legacy injected-thread warning. Normalized wheel and sdist
hashes matched across Windows/WSL2 at
`93daaefa6f39f57631af20ce75379809215e702d0c256cbd8e02e0c27c81f61f`
and `54099b731eaafa5c3bac16c4a8c945307433f0efeccf3e7a1fa31375a81f5d20`
respectively. Strict Twine, clean-wheel consumer smokes and offline
wheel/sdist installs in all six local OS/Python environments passed.
Development release validation remains `publishable: false`.

After the hostile-JSON preflight, focused runtime/bridge/docs tests passed
90 cases in each local Windows/WSL2 × Python 3.11–3.13 environment. Full
Python 3.13 suites passed Windows 585/73 and WSL2 644/14 (passed/skipped),
each with the same legacy injected-thread warning. The normalized wheel
SHA-256 matched across Windows/WSL2 at
`ce8b44b86da2f03c4644a186097f9b121454ad53af5c058a5d17ea639e968426`;
the sdist matched at
`ea7601092fe47159f36617f5c2360aac0da110fa9f86caba0e81d6ebe323d87d`.
Strict Twine, clean-wheel consumers and offline wheel/sdist installation
passed in all six local OS/Python environments. The development artifacts
remain non-publishable.

Real provider HITL semantics, Server/Connector authorized-decision routing,
durable host-side pending-request CAS, concurrent human decisions, and a
real Claude input/approval peer remain open. No native approval is automatic.
