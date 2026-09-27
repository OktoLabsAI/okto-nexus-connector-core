# HANDOFF — Nexus Server e Nexus Connector (C1/PC06)

Artefato de integração dos hosts. Valores de wheel/manifest finais são
preenchidos no gate PC14; este documento fixa o contrato de consumo.

## Composição pública (substitui imports privados)

```python
from nexus_connector_core import create_runtime

runtime = create_runtime(
    journal=my_journal,            # port Journal (kits de conformance)
    environment=resolve_overlay,   # async (prepared) -> Mapping[str, str]
    candidates={adapter_id: candidate},
    workspace_roots={workspace_id: "/abs/root"},
    # opcionais: owned_slot_ledger, clock, event_sink, budgets,
    # codex_client_info, codex_resume, pi_native_action,
    # native_approvals_enabled (default False)
)
```

- **Não importem** `nexus_connector_core.native.*`, `CopiedAdapterFactory`
  nem `offloop`. O parâmetro `native_factory` existe apenas para smokes
  de contrato com fakes.
- Lifecycle: `prepare → open → submit/control/events/inspect → close →
  shutdown`. `shutdown()` encerra sessões; o journal injetado **nunca** é
  fechado pelo Core (dono declarado: o host). O journal de referência
  agora tem worker próprio: prefiram `await journal.aclose()` em loops;
  `close()` síncrono permanece como ponte transitional.

## Mudanças que os hosts absorvem (C1)

| Mudança | Impacto |
|---|---|
| Journal/ledger off-loop (worker dedicado, filas bornadas) | Integrar startup/shutdown com `aclose`; `JOURNAL_BUSY` tipado indica backpressure antes de efeito; `JOURNAL_CLOSED` após encerramento; nenhum SQL bloqueia o loop do host |
| Fence de admissão em memória | Submits sob lease expirada/revogada/closing falham `AGENT_REVOKED`/`SESSION_CLOSING` imediatamente, sem depender de storage |
| Contenção independente | Expiração contém árvore própria sem esperar send/journal; force nunca cancelado no meio do bookkeeping; outcomes honestos (`unknown` retém slot) |
| Guarda pré-efeito | Efeitos não começam sob autorização vencida (inclusive threads tardias); recusas comprovadas viram not-sent durável |
| EOF de sessão | Perda inesperada do stream cerca a sessão (`EVENT_STREAM_UNAVAILABLE`) com incidente único por epoch; fecho esperado é silencioso |
| IDs 1–160 + legado | Gerem IDs ≤160; `legacy_operation_receipt(srv, exe, id)` consulta histórico dev0 de 161–256 (somente leitura, sem replay) |
| Factory pública | Substituir qualquer import privado por `create_runtime` |

## Callbacks obrigatórios/opcionais

- `environment` (obrigatório): overlay selado; nunca `NEXUS*` não
  autorizado (o Core recusa).
- `codex_client_info` / `codex_resume` / `pi_native_action`: seams
  confiáveis do host; o Core valida formas/identidade.
- `event_sink`: não-bloqueante do ponto de vista do Core (replay por
  cursor durável).
- `native_approvals_enabled=True` exige `approval.decide`+`input.provide`
  em todo contexto de lançamento.

## Erros novos/familia

`JOURNAL_BUSY` (backpressure pré-efeito, retry_safe), `JOURNAL_CLOSED`,
`AGENT_REVOKED` pré-efeito pós-await, `SESSION_CLOSING` no fence. Demais
códigos preservados.

## Pendências por owner

- Hosts N/C: integração real, pin de wheel/hash e campanhas conjuntas
  (PC13) — dependem dos projetos irmãos (não iniciados).
- Attach (PC12): trilha própria; capability continua desligada.
- Publicação/PyPI: sessão conjunta pendente (fora do escopo C1).


## Mudanças que os hosts absorvem (C2 — reauditoria R01–R10)

1. **Pi qualifica só por identidade portátil**: o fingerprint composto
   legado (Node+cli.js) deixou de ser grant de qualificação para
   `pi_rpc` (R06); identidade nova do build 0.87.1:
   `sha256:b454b39171e7428e721ecc01be6654c3608a9091d398c3d3d445897a91a67e43`.
   Binding local (path-bound) continua exigido à parte.
2. **`CodexResumeGrant` é público** (`from nexus_connector_core import
   CodexResumeGrant`) — a bridge valida o mesmo objeto; anotação real de
   `create_runtime(environment)` é
   `Callable[[PreparedLaunch], Awaitable[Mapping[str, str]]]` (R09).
3. **Discovery público composto**: `LocalRuntimeCore(pi_install_root=,
   pi_node=)` e `create_runtime(trusted_discovery_roots=,
   pi_install_root=, pi_node=)` — `discover()` compõe os releases Pi;
   versão do candidato vem do package.json do pacote (R08).
4. **Retry idempotente sobrevive a EOF/closing/evicção**: mesmo ID+hash
   devolve o recibo durável conhecido em vez de erro de sessão (R04).
5. **`cleanup_budget_seconds`** (default 5.0) no runtime/`create_runtime`:
   sink travado é cancelado cooperativamente na evicção sem avançar
   cursor; adaptador nativo liberado (R10).
6. **`journal.open_journal(path)`**: entrada assíncrona de construção
   (PC01.06/C2-§6); `aclose()` inalterado.
7. **Pool de controle reservado** na factory (`CopiedAdapterFactory.close()`
   para dispose); força/observação/close nunca disputam o executor
   default (R02). `containment_preflight` com ABI correta (prctl 37) e
   `require_containment` carregando os requisitos faltantes na mensagem
   (R07). Probes ativos (`probe_selected_*`) exigem contenção ANTES de
   spawnar.
8. **Semântica do manifesto NXL `core_version`** documentada como
   "introduced in" (0.1.0.dev0) — não é a versão do pacote produtor.
