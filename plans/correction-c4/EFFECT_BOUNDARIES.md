# EFFECT_BOUNDARIES — inventário de fronteiras de efeito (C4-00.03)

Operação pública → kernel → callbacks → pool → adapter → lock/IPC →
write/flush/spawn físico. "Concessão" = outorga de trabalho; "Contenção"
= negar/interromper/conter. Cada fronteira tem guarda e teste.

| Operação | Categoria | Última espera interna antes do efeito | Guarda na fronteira | Teste |
|---|---|---|---|---|
| `runtime.open` (spawn) | Concessão | fila do executor (`to_thread`) + callbacks environment/resume/native_action + `connector.start` | `_revalidate_launch` (deadline + `opening_guard` draining) + `_revalidate_content` (stat snapshot) no loop, no início da thread E dentro de `_guarded_start` | C4 t02(C3)/t04b/t05; s02/s01(C3) |
| `turn.submit` / steer / follow-up (Codex) | Concessão | `_CodexTransport._write_lock` (bounded acquire) | bridge `fence.check` (loop+thread) **e** `DispatchGuards.check()` após o lock, antes de `stdin.write` | **C4 t03** (transporte real) |
| idem (Pi) | Concessão | `_PiTransport._write_lock` | mesma guarda após o lock, antes de `stdin.write` | mesma mecânica (t03 cobre o mecanismo; transporte Pi idêntico por construção) |
| idem (Claude) | Concessão | `_acquire_write_lock` (bounded) | mesma guarda após o lock | idem |
| approval accept / input permissivo | Concessão | fila do executor + lock do transporte | `fence.check("approval_reply")` no loop, na thread E via `DispatchGuards` no transporte; revalida correlação turno/pedido na escrita | C3 s03 |
| approval deny / cancel | Contenção (nega) | fila + lock | SEM guarda de prazo (negar nunca concede); correlação/ownership exigidos | C3 s03 (deny permitido pós-prazo) |
| `turn.interrupt` | Contenção | lock do transporte | isento de prazo no fence (`{"interrupt","end"}`); ownership/corrente via bridge | campanhas reais C1 + test_pc02 |
| `runtime.close` | Contenção | `native.close()` (pool controle) | sem espera por lease; unknown conservador | test_runtime shutdown suite |
| força de emergência (`_force_after_deadline`) | Contenção independente | **nenhuma de storage** (C4/T01): despacho imediato no pool dedicado | identidade de ownership/geração; auditoria de journal em paralelo, rastreada | **C4 t01**; s05(C3); r02(C2) |
| probes ativos (`probe_selected_*`) | Diagnóstico autorizado | — | `require_containment()` ANTES de qualquer observer/spawn | r07b(C2) |
| renovação/revogação de lease (CAS) | Meta (não-efeito nativo) | worker do journal | reserva em memória curta; CAS fora dos locks; commit tardio aplicado conservadoramente; falha atomica = finalização evidenciada | s04(C3); **C4 t02** |

Invariantes transversais: nenhuma guarda depende do polling do watcher
(relógio vivo no fence); zero bytes comprovados ≠ bytes possíveis (pós-
escrita parcial → OUTCOME_UNKNOWN, nunca `not_sent`/`retry_safe`); força
nunca espera journal/observers/close; nenhum efeito de concessão após
draining; cancelamento de await nunca é prova de parada de thread.
