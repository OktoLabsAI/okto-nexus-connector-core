# Matriz de aceite

O status abaixo refere-se ao caso completo descrito no plano. Testes unitários
parciais não convertem automaticamente um gate em PASS.

| ID | Cenário | Status | Evidência |
|---|---|---|---|
| TK-01 | Import puro | PASS | Clean-wheel installation/import audits on Windows/WSL2 × Python 3.11–3.13: no socket/thread/process/secret-read/hidden loop on import; the wheel audit also rejects dynamic sibling imports, sys.path mutators and file-based module loading (`reproducible-build`, `runtime-sbom`, `wheel-import-audit`, `offline-six-env` evidence). |
| TK-02 | Deps | PASS | Dependency-tree/import-boundary audit of the isolated wheel (SBOM inventory included) shows no Nexus/Connector/FastAPI/dashboard/embedding imports or undeclared externals in the Core base (`runtime-sbom`, `wheel-import-audit` evidence). |
| TK-03 | Proveniência | PASS | Read-only source-to-Core SHA-256 inventory of the four copied adapters/helpers, excluded canonical supervisor/domain/ports, legacy tests and license text preserved, no canonical domain copied (`extraction-provenance-2026-09-25.md`). Legal license review remains a separate release gate (K11), not part of this comparison case. |
| TK-04 | API pública | PASS | Minimal clients (embedded and remote consumer smokes) use only documented exports/ports against the installed wheel; public docs tests pin export coverage and no private-class/DB/loop access (`consumer-smoke`, `consumer-conformance`, `offline-six-env` evidence). |
| TK-05 | Schemas | PASS | Bundled-schema frame codec validates positive/negative fixtures, closed fields, exact revision and event/inventory/unknown-receipt invariants before any effect; unknown security-relevant actions fail closed (`frame-codec`, `contract-bundle` evidence). |
| TK-06 | Intent hash | PASS | RFC 8785 canonicalization with Unicode/order vectors, retry-generation exclusion, NaN/infinite/duplicate-key denial and same-ID/different-hash conflict detection (`jcs-2026-09-25.md`, hash-vector fixtures). |
| TK-07 | Bundle | NOT_RUN | — (bundle remains `development-partial`; normative immutability requires consumer repinning that depends on the not-yet-started N/C projects). |
| TK-08 | Extração parity | PASS | Adapted legacy suites rerun per adapter on both local OSes (Codex 32, Pi 27+, Claude stream 29 on Windows; attach 57 on WSL2), preserving recorded expectations; divergences were fixed as explicit regressions (e.g. `CONTENT_TOO_LARGE` extraction) (`linux-wsl2`, extraction evidence). |
| TK-09 | Registry | PASS | Metadata-first registry: network-supplied module/factory paths are never imported; incompatible-platform and unknown-adapter selections raise typed errors with lazy static loading only (`native-registry` evidence). |
| TK-10 | Wheel inicial | PASS | Embedded and remote synthetic consumers run the same clean installed wheel through the documented API without either application (`consumer-smoke-2026-09-25.md`, repeated for every artifact pair). |
| TK-11 | Discovery | PASS | Fake cwd executables never execute, PATH wrappers rejected, stuck version probes fail with a bounded typed timeout, probes never read secrets (`discovery-probe` suite, both OSes). |
| TK-12 | Argv | PASS | Typed argv realization with spaces/Unicode paths, wrapper rejection and no shell concatenation, verified for Codex/Pi/Claude templates incl. the Node+CLI compound (`profiles`, `pi-node-cli-selection` evidence). |
| TK-13 | Root drift | PASS | Executable/symlink/config changes between prepare and open revalidate and deny with `PROFILE_DRIFT`/`NATIVE_VERSION_UNQUALIFIED` before spawn (`discovery-probe`, `profiles` suites; composite Pi fingerprint rechecks). |
| TK-14 | Auth home | PASS | Environment resolution only through approved local refs; provider homes/hooks require explicit trust; missing capabilities fail without leaking resolver errors or secrets to any peer (`environment` suite, `mcp-capability-env` evidence). |
| TK-15 | Config CAS | PASS | Plan/apply with adjacent cross-process lock, reread/hash CAS, backups preserving third-party entries, owned-field-only removal and explicit post-replace uncertainty (`config-persistence`, `codex-toml-merge`, `config-plan` evidence). |
| TK-16 | Journal efeito | PASS | Child-process crash cuts at journal and kernel effect boundaries on Windows and WSL2, including rollback of uncommitted inserts, survival of committed unknown/terminal/ACK facts, real owned-child cuts across spawn/write/ack/receipt and birth-record cuts; duplicate admission never replays the synthetic external effect (`journal-crash-2026-09-25.md`, `kernel-effect-crash-2026-09-25.md`, `process-birth-journal-crash-2026-09-26.md`). Scope: two local OSes, synthetic external effects. |
| TK-17 | Ownership | PARTIAL | — (Darwin-only scoped pass: the launchd-coalition owned-process backend passed its native synthetic campaign on the Intel macOS 26.4.1 host — 100/100 setsid/double-fork escapes with zero leaks, proven stops, census/slot/hygiene checks — `macos-native-acceptance-20261002`; the Windows/Linux ownership campaigns and real-provider qualification remain the gate for full PASS.) |
| TK-18 | Bounded output | PASS | Floods through real child stdout/stderr with per-session and global byte/item ceilings, noisy-session eviction, large-event preflight, slow-subscriber isolation with explicit gaps and targeted interrupt survival, continuous adapter draining with bounded subscriber queues (`native-event-fairness`, `codex-slow-subscriber-isolation` evidence; both local OSes). |
| TK-19 | Lease/timeout | NOT_RUN | — |
| TK-20 | Shutdown | NOT_RUN | — |
| TK-21 | Codex lifecycle | PASS | Real campaign Windows/x86_64, codex 0.157.0 (`codex-real-turn-controls-2026-09-26.md`): handshake, thread, three turns, native turn IDs, terminal `turn/completed` correlated before/at completion; process alive between turns ≠ active turn. Scope: one build/OS; no HITL/resume. |
| TK-22 | Codex control | PASS | Real Windows/x86_64 campaign (`real-control-hitl-closures-2026-09-26.md`): concurrent two-thread turns on one app-server, steer with the live expected turn ID, stale-ID steer refused before write, interrupt hit only its target turn (`completed` vs `interrupted`). Scope: one build/OS. |
| TK-23 | Codex HITL | PASS | Real provider (`real-control-hitl-closures-2026-09-26.md`): `item/commandExecution/requestApproval` declined through the checked host reply path (mapped to native `cancel`, no execpolicy amendment) and a tardy reply refused after turn end. Input elicitation denied/tardy paths remain synthetic contained-peer evidence (combined closure, noted). |
| TK-24 | Pi framing | PASS | Bounded byte/LF framing with fragmented UTF-8/CRLF/U+2028/U+2029 inside JSON and separated stderr proven against real contained child processes on Windows/WSL2 × Python 3.11–3.13 (`pi-byte-framing-2026-09-26.md`). Real-Pi sustained-load backpressure is outside this case's clauses. |
| TK-25 | Pi correlation | NOT_RUN | — |
| TK-26 | Pi settled | NOT_RUN | — |
| TK-27 | Claude stream | PASS | Combined (`claude-real-turn-controls-2026-09-26.md` + `real-control-hitl-closures-2026-09-26.md`): real multi-turn/deltas/system/result terminals, plus a slow consumer (25 ms/event) with continuous adapter drain — terminal preserved and last, no silent loss. Scope: one build/OS. |
| TK-28 | Claude control | PASS | Requesting-phase steer/interrupt refusal proven pre-write synthetically (`claude-control-2026-09-25.md`); generating-phase interrupt verified against real Claude 2.1.282 with `control_response:success` and honest `result:error_during_execution`, no no-op positive; queue-less interrupt-then-reprompt semantics published in `docs/adapters.md` (`claude-real-turn-controls-2026-09-26.md`). Scope: one build/OS. |
| TK-29 | Claude HITL/erros | PASS | Real provider (`real-control-hitl-closures-2026-09-26.md`): `control_request:can_use_tool` (Write) surfaced, forged tool kind refused before write, decline delivered via the checked reply path, `result:success` after denial; error terminal from the interrupt campaign. AskUserQuestion remains synthetic (combined closure, noted). |
| TK-30 | Attach target | NOT_RUN | — |
| TK-31 | Attach detach | NOT_RUN | — |
| TK-32 | Attach compatibility | NOT_RUN | — |
| TK-33 | Ports nativas não MCP | NOT_RUN | — |
| TK-34 | Configuração HTTP, sem MCP runtime | NOT_RUN | — |
| TK-35 | Pi extensão | PASS | Dependency-free extension with three explicit native tools shipped in wheel/sdist (offline installs verify the resource), narrow Core-owned loopback JSONL ingress, pinned local build with no fetch of `main`, structured params validated before the scoped backend, no model-text parsing (`pi-extension-2026-09-25.md`, `pi_extension_resource` tests). |
| TK-36 | Capabilities | PASS | Effective capability is the intersection of exact-build qualification × platform × architecture × observed request contracts: steer is refused for Claude, interrupt-only advertisement, managed work/execute_work stays false without the qualified bridge, and any drift loses the grant (`compatibility` allowlist/contract tests, per-adapter steer gates). |
| TK-37 | Fault matrix | NOT_RUN | — |
| TK-38 | SO real | NOT_RUN | — |
| TK-39 | Fuzz | PASS | Adversarial JSON at the frame codec (deep nesting, escaped duplicate keys, invalid Unicode, oversized numbers, cyclic/oversized host objects preflight), hostile journal/lease configuration values, native hostile JSON on real child stdout (duplicate keys, non-finite constants, non-object messages, deep parser recursion), unpaired-surrogate and out-of-range integer rejection, and bounded JSONL chunking - all on Windows/WSL2 × Python 3.11–3.13 with no parser loosening (`frame-codec`, `hostile-configuration`, `native-hostile-json`, Unicode streaming evidence). No payload-driven shell/import path exists; broader provider-text fuzz remains future hardening. |
| TK-40 | Fairness | PASS | Combined synthetic campaigns on Windows/WSL2: per-session/global byte-item caps with noisy-session eviction and large-event preflight, slow-subscriber isolation through real child stdout with targeted interrupt surviving saturation, four-process journal fairness across servers/sessions, a 100k-operation campaign, and sustained 45 s four-session runs (1,374/1,826 turns, 13,768/18,288 events) with bounded journals, zero faults and typed urgent-control outcomes (`core-engineering-closures-2026-09-26.md` and prior fairness evidence). Real-provider sustained load remains open and is not part of these clauses. |
| TK-41 | Journal alternativo | NOT_RUN | — |
| TK-42 | Packaging | NOT_RUN | — |
| TK-43 | Dois consumidores | NOT_RUN | — |
| TK-44 | Compat release | NOT_RUN | — |
| TK-45 | Publicação | NOT_RUN | — |
| J01 | Identidade canônica | NOT_RUN | — |
| J02 | Não rotacionar para conectar | NOT_RUN | — |
| J03 | Autenticação errada | NOT_RUN | — |
| J04 | Nexus local puro | NOT_RUN | — |
| J05 | Servidor realmente remoto | NOT_RUN | — |
| J06 | Rede outbound | NOT_RUN | — |
| J07 | Paths heterogêneos | NOT_RUN | — |
| J08 | 100 mil agentes | NOT_RUN | — |
| J09 | Um daemon, várias identidades | NOT_RUN | — |
| J10 | Dois Servers | NOT_RUN | — |
| J11 | First-use/second-use | NOT_RUN | — |
| J12 | Daemon automático | NOT_RUN | — |
| J13 | Terminal independente | NOT_RUN | — |
| J14 | Turno versus processo | NOT_RUN | — |
| J15 | Shutdown/crash | NOT_RUN | — |
| J16 | MCP HTTP tools-only direto | NOT_RUN | — |
| J17 | Work bridge nativa não MCP | NOT_RUN | — |
| J18 | Consumo exclusivo | NOT_RUN | — |
| J19 | HITL concorrente | NOT_RUN | — |
| J20 | Recebido não é concluído | NOT_RUN | — |
| J21 | Resposta perdida | NOT_RUN | — |
| J22 | Partição e revogação | NOT_RUN | — |
| J23 | Gerações e takeover | NOT_RUN | — |
| J24 | Eventos/retention | NOT_RUN | — |
| J25 | Saturação | NOT_RUN | — |
| J26 | Drift/config segura | NOT_RUN | — |
| J27 | Quatro adapters | NOT_RUN | — |
| J28 | Upgrade/rollback | NOT_RUN | — |
| J29 | Segredos/ameaças | NOT_RUN | — |
| J30 | Release coordenado | NOT_RUN | — |
| J31 | Remoção MCP stdio | NOT_RUN | — |
| J32 | MCP HTTP local nativo | NOT_RUN | — |
| J33 | Fronteira protocolo/transporte | NOT_RUN | — |
| J34 | Dois canais e autorização | NOT_RUN | — |
