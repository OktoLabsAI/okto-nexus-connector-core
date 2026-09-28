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


## Mudanças que os hosts absorvem (C3 — reauditoria S01–S08)

1. **Fonte temporal única**: `create_runtime` sem clock usa o
   `SystemClock` real compartilhado runtime/kernel/factory — a proteção
   temporal NUNCA depende de parâmetro de teste (S01).
2. **`CoreError.message`**: campo novo aditivo; `code` é o enum estável
   (ex.: `PROCESS_CONTAINMENT_UNAVAILABLE`); detalhes redigidos vão na
   mensagem — CLI/Server classificam por `code` (S07).
3. **Guarda no efeito físico**: spawn revalida dentro da thread;
   respostas permissivas de aprovação/input compartilham o
   `EffectFence` (negações seguem permitidas pós-prazo) (S02/S03).
4. **CAS de lease**: fora dos locks de contenção; commit tardio após
   cancelamento é aplicado conservadoramente; timeout = `RECONNECT_BUSY`
   / `REVOKE_BUSY` — nunca prova de ausência de efeito (S04).
5. **Capacidade de força dedicada** (`nexus-core-force`) + observações
   coalescidas por sessão; shutdown público dispõe os executores da
   factory quando tudo está resolvido (idempotente) e RETÉM sob
   ownership incerto (S05/S08).
6. **Identidade Pi v2**: cobertura completa por dependência
   (manifesto de conteúdo); nova qualificação real
   `sha256:bc3b22f8…4284914`; digests v1 não qualificam (S06).
7. Versão mínima esperada pelos hosts: **0.2.2.dev0**.


## Mudanças que os hosts absorvem (C4 — reauditoria T01–T07)

1. **`create_runtime(cleanup_budget_seconds=…)`** exposto (default 5.0).
2. **Seam aditivo `opening_guard`** em `NativeFactory.open` (opcional;
   factories legadas seguem funcionando): o runtime fecha o guard de
   aberturas pendentes no início do shutdown — nenhum spawn tardio.
3. **`CoreError.message`** (C3) segue o contrato código-estável;
   `RUNTIME_DRAINING` pode chegar de aberturas drenadas (retry_safe).
4. **CAS de lease**: falhas comprovadamente sem commit liberam a
   tentativa (retry imediato após recuperação); commit tardio após
   cancelamento é aplicado conservadoramente; BUSY documenta unidade em
   voo — sem reset de sessão como workaround.
5. **Identidade Pi v3** (`core.build_identity.v3`): relations
   optional/peer instaladas cobertas, ausências registradas, topologia
   lógica; nova qualificação real
   `sha256:caf8bfad84ea26a7c8eaee06e0cde3dd7e34ef05e00dbebc348dfb3f22de487b`.
6. **Guarda na fronteira nativa** (`DispatchGuards`): os três
   transportes revalidam após seus locks, antes do primeiro byte.
7. Versão mínima esperada pelos hosts: **0.2.3.dev0**.


## Mudanças que os hosts absorvem (C5 — reauditoria U01–U07)

1. **Aprovações permissivas/input**: a guarda (prazo + correlação
   pedido/turno) alcança o escritor nativo APÓS o lock do transporte;
   zero bytes comprovados em recusa. Negações seguem permitidas
   pós-prazo (U01).
2. **`_launch_guard` nos adapters**: o criador nativo (Codex/Pi/Claude)
   revalida prazo+draining após seus locks internos, imediatamente antes
   do spawn — seam interna; hosts não a configuram (U02).
3. **Opens cancelados**: o Core supervisiona o producer e contém handle
   tardio (close→observe→force); `_uncertain_opens` só resolve com
   parada comprovada. Sem API nova para o host (U03).
4. **Força antecipável**: shutdown mais urgente antecipa contenção
   agendada (deadline mínimo); dispatch em voo nunca cancelado (U04).
5. **CAS pós-commit incerto**: erro com `possible_effect=True` reconcilia
   pelo registro durável; revogação comitida fecha cercas mesmo com
   confirmação perdida; hold conservador quando storage ilegível (U06).
6. **Seal de lançamento Pi**: Node + CLI + fechamento de dependências
   (stat-only) revalidado em todas as fronteiras; mudança ordinária de
   CLI/dependência pós-prepare = `PROFILE_DRIFT` (U05).
7. Versão mínima esperada pelos hosts: **0.2.4.dev0**.


## Mudanças que os hosts absorvem (C6 — reauditoria V01–V03 + M01)

1. **`LEASE_UPDATE_PENDING`** (novo código estável, retry_safe, sem
   possible_effect): submits/steers/approvals permissivos recusados
   enquanto uma atualização de lease (tipicamente revogação) está
   reservada ou em estado durável incerto; deny/interrupt/force/observe
   e recibos já conhecidos seguem disponíveis (V01).
2. **REVOKE_BUSY/RECONNECT_BUSY** documentados: podem significar
   confirmação pendente, não ausência de efeito durável — reconciliação
   automática coalescida com backoff; nada para o host fazer além de
   aguardar/consultar (V01).
3. **Opens cancelados**: a tentativa sobrevive ao waiter (shutdown
   continua cercando); handle tardio com parada não comprovada fica
   fortemente possuído pelo Core (`_late_handles`) e é re-contido em
   shutdowns subsequentes; close gracioso tem orçamento — close travado
   nunca bloqueia a força (V02).
4. **Aprovações**: recusa comprovadamente pré-byte (zero bytes) devolve
   a reserva — o MESMO pedido pode ser negado depois; após bytes
   possíveis o pedido permanece consumido (V03).
5. **Enumeração**: fronteira cap+1 exata (M01).
6. Versão mínima esperada pelos hosts: **0.2.5.dev0**.


## Mudanças que os hosts absorvem (C7 — reauditoria W01–W04)

1. **Aprovações negativas após o prazo produtivo**: `decline`/`cancel`
   a um pedido ainda observado (mesmo turno/identidade/geração) seguem
   pela API pública após o vencimento da lease e em sessão
   closing/faulted — classificadas como contenção (como
   `turn.interrupt`); `accept`/input com conteúdo continuam recusados
   com zero efeitos (W04).
2. **Recovery de lease**: falha comprovadamente pré-entrega converge
   quando o storage responde (hold liberado com prova, nunca por
   tempo); ACK perdido pós-commit continua UNKNOWN com hold (W02).
3. **Handles tardios**: ownership registrada antes de qualquer await;
   close cancelado cooperativamente nunca precondiciona a força
   (paralela); parada não comprovada mantém o handle fortemente
   registrado e o próximo shutdown público o re-contém (W03).
4. **Sessão ausente**: submit/steer retornam `SESSION_UNKNOWN` tipado
   (nunca AttributeError); replay de recibos conhecidos continua
   disponível pós-evicção (W01).
5. Versão mínima esperada pelos hosts: **0.2.6.dev0**.


## Mudanças que os hosts absorvem (C8 — reauditoria X01–X03)

1. **Contexto superseded**: quando o Core observa uma fence durável
   mais nova (outro writer autorizado avançou a lease), o contexto
   local fica sabidamente obsoleto — submits/steers/accepts recebem
   `STALE_GENERATION`/`AGENT_REVOKED`; contenção (deny/interrupt/force)
   e recibos conhecidos seguem disponíveis; o encerramento/reconcile é
   do host autorizado (X01).
2. **Release durável**: uma parada comprovada com release recusado
   mantém obrigação identificável; o próximo `shutdown()` público
   re-tenta e converge (idempotente) (X02).
3. **Coalescência física**: repetidos shutdowns compartilham a unidade
   de força em voo (uma por recurso); nova unidade só após conclusão;
   recurso já parado é observado e nunca re-forçado (X03).
4. Versão mínima esperada pelos hosts: **0.2.7.dev0**.


## Mudanças que os hosts absorvem (C9 — catálogo + recuperação)

1. **Catálogo público (o primeiro contrato do seletor)**:
   `get_runtime_catalog()` → `RuntimeCatalog(core_version,
   format_version, runtimes)` com `RuntimeDescriptor` por adapter
   (`adapter_id`, `display_name`, `harness_family`, `native_kind`,
   `connection_mode`, `implementation_platforms`, `support_status`,
   `discoverable`). Server/Connector/UI enumeram por essa API — **sem
   arrays próprios e sem `native.registry`**; `claude_attach` =
   `registered_unqualified` (nunca elegível por existir).
2. **`DiscoveryRequest(adapter_ids=None)`**: pergunta ao catálogo quais
   adapters admitem discovery neste host; tupla explícita continua
   filtro; IDs desconhecidos recusados como antes.
3. **Gerador de contratos** deriva os enums do registry (fonte única);
   os schemas regenerados são byte-idênticos — nenhum impacto em
   consumidores atuais.
4. **Y01**: a contenção de handles tardios nunca é gated por observação
   travada (cache do último estado; observe = unidade própria
   orçamentada).
5. **Y02**: shutdown é orçamentado mesmo com release durável pendente;
   obrigação + release em voo sobrevivem ao timeout e convergem no
   próximo lifecycle; contenção de recursos vivos roda antes das
   liberações duráveis.
6. Versão mínima esperada pelos hosts: **0.2.8.dev0** (a validação
   recomenda iniciar Connector e integração Server AGORA, com este wheel
   pinado).
