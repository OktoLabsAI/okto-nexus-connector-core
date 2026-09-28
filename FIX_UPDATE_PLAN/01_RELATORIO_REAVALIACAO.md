# Reavaliação do Core após C6 — 12dae55

## Conclusão

A versão `0.2.5.dev0`, snapshot `12dae55381a9871958c7ffb7513030eaa66886c2`, resolveu as reproduções principais da revisão anterior. Há quatro grupos confirmados nesta rodada: W03 (P1, contenção/recuperação tardia), W02 (P2, convergência de lease), W04 (P2, resposta negativa pela API pública) e W01 (P2, erro tipado de sessão ausente). Não recomendo reescrita nem reabertura de todo o plano original.

A nova campanha contém nove casos: oito falham e um controle positivo passa. O resultado foi repetido. Não foram procurados requisitos novos para exigir outra rodada: W02–W04 correspondem a garantias explicitadas no C6; W01 é uma regressão localizada introduzida pelas novas condições de hold.

Não ratifico E1 para os caminhos afetados enquanto W03 permitir que a força dependa da conclusão de outra operação ou que a recuperação não alcance o handle disponível. Esta é uma conclusão delimitada; ela não invalida a correção dos casos antigos nem os testes funcionais que passam. Os consumidores podem continuar a integração experimental com versão fixada. E2 não foi executado.

## 1. Base, escopo e integridade

A fonte de verdade foi o ZIP enviado `okto-nexus-connector-core-main(4).zip`. Seu comentário identifica o commit acima e o pyproject declara a versão. Comparei os arquivos com o snapshot anterior `df3baaf` e li C6 e as evidências do executor.

Foram preservados os **366 arquivos originais**. O manifesto registra SHA-256 de cada arquivo e do ZIP. Builds ocorreram numa cópia separada. As regressões novas estão fora da árvore do produto. As consultas ao GitHub usaram o mesmo commit, somente para conferir âncoras; não foram usadas mudanças da branch atual para avaliar o ZIP.

Ambiente desta revisão: Python 3.13.5/Linux. PyPI estava indisponível. A dependência rfc8785 0.1.4 foi recuperada do upstream pelo conector GitHub e copiada byte a byte para o ambiente de auditoria; os dois Git blob SHAs foram verificados. Não foi usado stub nem substituição do algoritmo. Jsonschema 4.26.0 e pytest 9.0.2 estavam instalados. O ambiente de importação isolada usa o wheel instalado fora do checkout e um .pth para as dependências da auditoria; detalhes em `evidencias/environment.json`.

## 2. Campanhas executadas

| Campanha | Resultado |
|---|---|
| Testes C6 reconstruídos no repositório | 6 PASS |
| Sementes C6 originais, sem adaptação | 5 PASS, 1 falha de barreira incompatível |
| Mesmas sementes C6, adaptação mínima documentada | 6 PASS |
| Sementes C5 originais fornecidas no pacote anterior | 11 PASS |
| Testes C5 entregues no snapshot | 11 PASS |
| C2/C3/C4 histórico | 44 PASS, 1 SKIP |
| Regressões novas finais | 8 FAIL, 1 PASS |
| Repetição final, incluindo esgotamento completo de recovery | 8 FAIL, 1 PASS |
| Suíte completa | 690 PASS, 123 FAIL, 20 SKIP, 2 warnings |
| Wheel/sdist pelo backend setuptools | PASS |
| Importação instalada com `-I` | PASS após corrigir dependências do ambiente |
| Bundle instalado com opt-in development-partial | PASS |
| Exemplos embedded/remote instalados | Ambos OK; são consumidores sintéticos |

Subconjuntos e repetições se sobrepõem. Não se devem somar essas linhas para produzir uma contagem de testes únicos. As primeiras execuções das novas regressões também foram preservadas; a versão final deixa as 20 tentativas de recovery terminarem, para não confundir falta de convergência com um limite arbitrário de latência.

### A única adaptação de fixture C6

O teste antigo de referência forte esperava duas observações. O novo algoritmo observa uma vez, depois da força. A barreira não era atingida, embora a retenção estivesse correta nesse caminho. Alterei apenas `observations >= 2` para `observations >= 1`; as asserções de garbage collection, incerteza e retenção permaneceram iguais. O teste passou. O diff está em `evidencias/fixture_c6.diff`. **Não classifiquei essa incompatibilidade de fixture como bug.**

### As 123 falhas da suíte completa

Os agrupamentos por assinatura foram: 86 casos de capacidade de processos esgotada por árvores de parada não comprovada; 24 probes sem comprovação de parada; 11 recusas de preflight; um caso de cleanup do guardian não demonstrado; um caso de expectativa de preflight passivo. O sandbox não dispõe de `proc_children` esperado pelo backend. Não removi o gate nem transformei esses resultados em PASS. A classificação não prova a correção do backend em outro SO: a campanha real precisa ser executada onde o mecanismo existe.

Os quatro achados W foram reproduzidos separadamente dessas falhas. Providers reais, Windows/WSL2 e integração Server–Connector em dois hosts não foram executados por mim. As evidências que o executor apresenta desses ambientes continuam identificadas como suas, não como campanhas reproduzidas nesta revisão.

## 3. W03 — Contenção tardia ainda sequencial e recovery incompleta

**Prioridade P1.** Âncoras: `runtime.py:1653–1730`, `shutdown:975–1130`, `_consume_late_open` e `_late_handles`. Requisito anterior: C6-02.03–06.

### Close que ainda precisa concluir seu cancelamento

A implementação utiliza `await asyncio.wait_for(close(), timeout=cleanup_budget_seconds)` e só então chama `force_stop()`. Uma coroutine que, ao ser cancelada, ainda aguarda um recurso ou uma unidade nativa impede que essa espera termine. O timeout não estabelece por si só capacidade independente para a força.

A regressão inicia uma abertura autorizada, cancela apenas o chamador, pede shutdown zero e recebe o handle tardio. Close observa `CancelledError` mas continua esperando sua barreira. Enquanto essa barreira permanece fechada, a força não é chamada. Ao final do teste todas as barreiras são liberadas para cleanup.

Isso não demonstra um provider real travado; demonstra quebra do contrato com uma implementação controlável do port nativo. A independência exigida pelo C6 precisa sobreviver ao cleanup lento, não depender de a coroutine obedecer imediatamente ao cancelamento.

### Observer bloqueado deixa handle fora do recovery

A segunda regressão devolve um handle cujo close retorna unknown, cuja primeira força falha temporariamente e cujo observer aguarda. O shutdown esgota o orçamento e cancela a tarefa de cleanup. O registro em `_late_handles` ainda não aconteceu: ele aparece somente depois da observação.

Depois de liberar o observer e chamar shutdown novamente, o contador de força permanece em **um**. `_opening` ainda contém a tentativa, mas `_late_handles` está vazio e não há cleanup ativo. Portanto, não alego que o objeto foi coletado: o problema demonstrado é **o lifecycle público não recuperar o recurso que continua disponível**.

Correção: registrar antes do primeiro await e transferir o handle ao supervisor comum, com força agendada independentemente, tasks possuídas e retry sobre o mesmo owner. O C7 detalha esses estados. Não basta outro timeout, nem colocar o handle em um dicionário somente depois de uma chamada potencialmente bloqueante.

Testes: `test_w03_force_does_not_wait_for_close_cancellation_to_finish` e `test_w03b_second_shutdown_can_retry_late_handle_after_observer_stalls`.

## 4. W02 — Recovery termina com lease presa mesmo após falha segura comprovada

**Prioridade P2.** Âncoras: `runtime.py:1732–1847`, finalizador e reconciliador; C6-01.01–05.

O finalizador direto recebe `producer_done`. Se a consulta ao journal falha, ele agenda um reconciliador que não conserva essa informação e implementa outra classificação. Ao observar a linha anterior, esse laço espera que o produtor ainda possa comitar, mesmo quando ele já terminou antes de entregar qualquer escrita.

Executei renew e revoke com um Journal real, substituindo somente o ponto do CAS para devolver `JOURNAL_FULL`, `retry_safe=True`, `possible_effect=False` antes de enfileirar. A primeira leitura de recuperação falha. As leituras seguintes voltam a consultar o SQLite e confirmam a linha anterior não revogada.

**Deixei completar as 20 tentativas reais do reconciliador.** Nos dois casos houve 21 leituras contando a primeira falha; a tarefa terminou, mas `lease_hold=True` e `lease_cas_pending=True`. Uma submissão nova com autorização ainda válida recebe `LEASE_UPDATE_PENDING` e não chega ao peer.

Não é nova concessão indevida sob revogação. O hold funciona para segurança; falta a transição comprovada para recuperar disponibilidade. Também não recomendo removê-lo por tempo: o port deve conservar prova de término/resultado da tentativa e todos os caminhos devem usar um único finalizador. ACK perdido após commit continua distinto de erro pré-entrega.

Testes: `test_w02_recovery_finishes_failed_attempt_when_old_row_is_proven[renew]` e `[revoke]`.

## 5. W04 — O adaptador consegue negar após o prazo, mas a API pública não

**Prioridade P2.** Âncoras: `runtime.py:607–729,2288–2294,2332–2362`; `kernel.py:22–39`. Requisito anterior: C6-01.02 e C6-03; a negativa precisa continuar possível no escopo autorizado.

A regra de contenção temporal do Core e do kernel só inclui `turn.interrupt` e `runtime.close`. `decide_native_approval` trata decline/cancel como se concedessem trabalho e exige lease produtiva viva também em `_session`.

A regressão abre uma sessão, observa duravelmente um pedido válido, avança o relógio além da lease e chama a API pública. **Decline e cancel recebem AGENT_REVOKED e nenhuma resposta chega ao peer.** No mesmo cenário, accept também é recusado; esse é o controle positivo que deve permanecer passando.

O teste não usa token de rede vencido nem outro agente. É o contexto já autorizado do host com a lease local de trabalho expirada, ainda dentro da janela de contenção e com o mesmo pedido/turno. A exceção para negar não pode remover autenticação, capability, geração, identidade ou correlação.

Correção: classificação derivada da operação validada e compartilhada por `_authorize`, `_session`, kernel e writer. Isentar toda a ação `approval.decide` seria errado porque também liberaria accept. O C7 exige testar o caminho público, não apenas a bridge que já funciona.

Testes: `test_w04_public_approval_distinguishes_containment_from_new_permission[decline/cancel/accept]`.

## 6. W01 — Sessão ausente produz AttributeError

**Prioridade P2.** Âncora: `runtime.py:743–783`.

Em `_send`, `fence_binding=None` é tolerado inicialmente para que a checagem posterior `_session` produza SESSION_UNKNOWN. Contudo, o novo elif acessa `fence_binding.lease_expired` antes de chegar a essa validação. Submit e steer de uma sessão nunca existente lançam `AttributeError("'NoneType' object has no attribute 'lease_expired'")`.

É uma regressão pequena, mas afeta um erro normal de API: ID incorreto, binding removido ou sessão ainda não iniciada. Não houve efeito nativo. A correção é localizada e precisa preservar o lookup de recibos conhecidos antes de exigir sessão viva, pois replay após evicção é funcionalidade válida.

Testes: `test_w01_unknown_session_returns_typed_error[submit/steer]`.

## 7. Entrega e interpretação da liberação

O plano C7 tem seis fases e 25 tarefas. A matriz tem 36 cenários: oito FAIL, onze PASS, dezesseis NOT_RUN e um BLOCKED nesta revisão. Linhas de campanha e cenário se sobrepõem; isso não significa 36 testes implementados. Os nove casos novos executáveis estão no pacote, junto às sementes anteriores necessárias.

Priorize W03, complete W02 e W04, e corrija W01 sem ampliar a arquitetura. Não há motivo para duplicar adapters em Server/Connector ou reintroduzir MCP stdio. Os componentes podem continuar integração experimental com artefato fixado. A correção de W01 isolada não habilita E1; a evidência de contenção e recovery precisa corresponder ao contrato prometido.

Este relatório não é prova de ausência universal de defeitos. Ele diferencia o que foi corrigido, o que falhou de maneira reproduzível e o que não foi executado. **Nenhum código do produto foi modificado.**
