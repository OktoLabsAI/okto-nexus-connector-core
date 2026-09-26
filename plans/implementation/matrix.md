# Matriz de aceite

O status abaixo refere-se ao caso completo descrito no plano. Testes unitários
parciais não convertem automaticamente um gate em PASS.

| ID | Cenário | Status | Evidência |
|---|---|---|---|
| TK-01 | Import puro | NOT_RUN | — |
| TK-02 | Deps | NOT_RUN | — |
| TK-03 | Proveniência | NOT_RUN | — |
| TK-04 | API pública | NOT_RUN | — |
| TK-05 | Schemas | NOT_RUN | — |
| TK-06 | Intent hash | NOT_RUN | — |
| TK-07 | Bundle | NOT_RUN | — |
| TK-08 | Extração parity | NOT_RUN | — |
| TK-09 | Registry | NOT_RUN | — |
| TK-10 | Wheel inicial | NOT_RUN | — |
| TK-11 | Discovery | NOT_RUN | — |
| TK-12 | Argv | NOT_RUN | — |
| TK-13 | Root drift | NOT_RUN | — |
| TK-14 | Auth home | NOT_RUN | — |
| TK-15 | Config CAS | NOT_RUN | — |
| TK-16 | Journal efeito | NOT_RUN | — |
| TK-17 | Ownership | NOT_RUN | — |
| TK-18 | Bounded output | NOT_RUN | — |
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
| TK-35 | Pi extensão | NOT_RUN | — |
| TK-36 | Capabilities | NOT_RUN | — |
| TK-37 | Fault matrix | NOT_RUN | — |
| TK-38 | SO real | NOT_RUN | — |
| TK-39 | Fuzz | NOT_RUN | — |
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
