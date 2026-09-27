# Correção C2 — achados R01–R10 da reavaliação de `e6b6305`

Fonte: `FIX_UPDATE_PLAN/RELATORIO_REAVALIACAO_CORE_E6B6305.md` (reauditoria
independente, 14 testes falhando, 10 achados confirmados) e
`FIX_UPDATE_PLAN/02_ACOES_PARA_O_AGENTE.md`. Ordem de execução: §7 do
relatório.

| Fase | Achados | Sementes | Estado |
|---|---|---|---|
| C2-1 | R01+R04 (lock global sem I/O; dedup idempotente) | r01, r01b, r04 | DONE |
| C2-2 | R02 (capacidade reservada de controle/observação) | r02 | DONE |
| C2-3 | R03 (guarda com relógio real; revalidação no spawn) | r03, r03b | DONE |
| C2-4 | R05 (notificações coalescidas do worker) | r05 | DONE |
| C2-5 | R07 (ABI prctl correta; probes ativos sob o gate) | r07, r07b | DONE |
| C2-6 | R06 (raiz/dependências da identidade Pi; allowlist) | r06, r06b | DONE |
| C2-7 | R08 (discovery público composto) | r08 | DONE |
| C2-8 | R09 (DTOs públicos de resume; anotação environment) | r09 | DONE |
| C2-9 | R10 (ownership pós-evicção com sink travado) | r10 | DONE |
| C2-10 | §5/§6 (matriz precisa, journal assíncrono, preflight Win32, manifesto, artefato, decisão E) | — | DONE (decisão abaixo) |

Regras herdadas: sementes `xfail(strict=True)` até a fase cair; nenhuma
gate de contenção removida para ficar verde; unknown conservador segue
sendo resposta válida; sem MCP stdio/proxy; sem executar wrappers.

## Decisão de entrega (critérios §8 da reauditoria)

- 14/14 sementes passam com as invariantes preservadas (nenhuma falha
  apagada, nenhum esperado trocado, nenhum xfail/skip).
- Suítes completas verdes em 6 ambientes (Windows/WSL2 × 3.11–3.13).
- **E1 (Core corrigido em escopo delimitado) declarado** para `0.2.1.dev0`.
  E2/E3 continuam bloqueados pelos hosts reais (N/C), attach qualificado,
  billing/CI e sessão PyPI — ver `plans/correction-c1/PENDENCIAS.md`.
- **Sem publicação/push além do fluxo normal já acordado** com o usuário.
