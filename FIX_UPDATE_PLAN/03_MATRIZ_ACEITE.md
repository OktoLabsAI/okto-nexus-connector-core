# Matriz de aceite C6

**37 cenários. Estados desta auditoria:** {'FAIL': 7, 'NOT_RUN': 24, 'PASS': 5, 'BLOCKED': 1}. A matriz não equivale a 37 testes já implementados. Os sete FAIL incluem seis novas parametrizações e M01 da semente original; cinco PASS são controles/campanhas delimitados, não qualificação E1/E2. Os demais são critérios a executar.

O estado BLOCKED indica limite da campanha nesta auditoria, não falha comprovada do produto. Cada implementação deve atualizar estado, node executado, ambiente, commit e evidência sem apagar o baseline.

## AC6-01-01 — Cancelamento, commit real e confirmação perdida

**Achado:** V01. **Camada:** fault injection + SQLite real. **Estado no snapshot:** FAIL.

**Preparação:** Sessão autorizada; CAS real com barreira antes do commit.

**Ação:** Cancelar o chamador, liberar CAS que comita revoked=True e perde ACK; submeter com contexto anterior.

**Resultado exigido:** Nenhum send_turn; tentativa reconciliada pelo finalizador tardio, sem reabrir autorização.

**Evidência:** regressoes/test_c6_review.py::test_v01_uncertain_revocation_never_allows_old_work[cancel_then_lost_ack]

## AC6-01-02 — Commit confirmado pelo banco e leitura de recuperação indisponível

**Achado:** V01. **Camada:** fault injection + SQLite real. **Estado no snapshot:** FAIL.

**Preparação:** Wrapper confirma revogação e lança erro; leitura usada pelo Core fica indisponível.

**Ação:** Submeter novo trabalho enquanto não é possível ler o resultado da revogação.

**Resultado exigido:** Bloqueio produtivo explícito; reserva CAS não substitui esse bloqueio.

**Evidência:** regressoes/test_c6_review.py::test_v01_uncertain_revocation_never_allows_old_work[read_unavailable_after_commit]

## AC6-01-03 — Armazenamento retorna e a tentativa converge

**Achado:** V01. **Camada:** fault injection. **Estado no snapshot:** NOT_RUN.

**Preparação:** Mesma tentativa AC6-01-02, guardada em UNKNOWN.

**Ação:** Restaurar leitura; executar retry coalescido ou retomada pública documentada.

**Resultado exigido:** Revogação confirmada aplicada, sem novo trabalho intermediário nem duplicação de CAS.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-01-04 — Erro comprovadamente anterior à entrega

**Achado:** V01. **Camada:** contract. **Estado no snapshot:** NOT_RUN.

**Preparação:** Journal recusa antes de aceitar unidade e fornece prova tipada.

**Ação:** Executar revoke/renew e uma nova tentativa válida.

**Resultado exigido:** Finalizar apenas a reserva antiga; permitir progresso quando autorização vigente realmente permite.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-01-05 — Todas as entradas produtivas observam o hold

**Achado:** V01. **Camada:** unit + transport. **Estado no snapshot:** NOT_RUN.

**Preparação:** Sessão em hold de revogação com prazo ainda válido.

**Ação:** Tentar submit, steer, input e accept; consultar recibo de operação já conhecida.

**Resultado exigido:** Zero novos efeitos; recibo autorizado continua consultável e sem reenvio.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-01-06 — Controles seguros durante confirmação pendente

**Achado:** V01. **Camada:** fault injection + backend. **Estado no snapshot:** NOT_RUN.

**Preparação:** Revogação ambígua/read travado; alvo próprio confirmado.

**Ação:** Pedir deny/interrupt/force/observe nos caminhos válidos.

**Resultado exigido:** Controle não concede trabalho nem aguarda resolução de storage; ownership/correlação continuam exigidos.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-01-07 — Callback de tentativa antiga não altera a nova

**Achado:** V01. **Camada:** unit determinístico. **Estado no snapshot:** NOT_RUN.

**Preparação:** Duas revisões e tokens, resultado antigo atrasado.

**Ação:** Concluir callback antigo depois de criar/admitir tentativa posterior conforme contrato.

**Resultado exigido:** Nenhuma limpeza de reserva alheia, regressão de revisão ou reabertura de fence.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-01-08 — CAS tardio depois de shutdown

**Achado:** V01. **Camada:** fault injection. **Estado no snapshot:** NOT_RUN.

**Preparação:** CAS aceito; chamador cancelado; Core em draining.

**Ação:** Liberar commit/ACK após shutdown.

**Resultado exigido:** Atualiza evidência necessária, sem reativar runtime, spawns ou efeitos; recursos só dispostos quando resolvidos.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-01-09 — Linha observada não corresponde à proposta

**Achado:** V01. **Camada:** contract. **Estado no snapshot:** NOT_RUN.

**Preparação:** Lease com owner/config/auth/connection distintos, ou registro ausente com produtor ainda possível.

**Ação:** Recuperar após erro sem prova suficiente.

**Resultado exigido:** Não inferir rollback/commit por coincidência parcial; estado conservador ou stale explícito.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-01-10 — Repetição e pressão de recuperação

**Achado:** V01. **Camada:** load controlado. **Estado no snapshot:** NOT_RUN.

**Preparação:** Muitos pedidos repetidos para a mesma tentativa incerta.

**Ação:** Manter storage indisponível e cancelar waiters; depois restaurar.

**Resultado exigido:** Fila e tarefas limitadas/coalescidas, sem exceções não coletadas e sem redisparar trabalho.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-01 — Handle tardio com close travado

**Achado:** V02. **Camada:** fault injection. **Estado no snapshot:** FAIL.

**Preparação:** Open cancelado; produtor devolve peer; close bloqueado por Event.

**Ação:** Executar shutdown de orçamento zero e manter close retido.

**Resultado exigido:** Força chega ao peer sem liberar close; resultado só vira STOPPED após observação.

**Evidência:** regressoes/test_c6_review.py::test_v02_late_open_force_is_independent_of_hung_close

## AC6-02-02 — Handle desconhecido permanece possuído

**Achado:** V02. **Camada:** lifecycle + weakref. **Estado no snapshot:** FAIL.

**Preparação:** Close retorna unknown; força falha; observe retorna RUNNING.

**Ação:** Aguardar finalização do cleanup; remover referências da fixture e executar coleta de lixo.

**Resultado exigido:** Handle permanece no registro de ownership para novas tentativas; ID em conjunto não é suficiente.

**Evidência:** regressoes/test_c6_review.py::test_v02b_unconfirmed_late_handle_remains_owned_for_recovery

## AC6-02-03 — Open cancelado antes do shutdown, callback liberado depois

**Achado:** V02. **Camada:** factory/kernel/adapter reais + spawn sentinela. **Estado no snapshot:** FAIL.

**Preparação:** Environment retido; open cancelado; tentativa ainda pode produzir start.

**Ação:** Shutdown público, depois liberar callback.

**Resultado exigido:** Guarda continua alcançável pelo shutdown; primitiva spawn não chamada.

**Evidência:** regressoes/test_c6_review.py::test_v02c_shutdown_fences_cancelled_open_before_late_start

## AC6-02-04 — Recuperação do handle que não parou

**Achado:** V02. **Camada:** fault injection. **Estado no snapshot:** NOT_RUN.

**Preparação:** Estado de AC6-02-02 mantido no Core.

**Ação:** Restaurar backend de força e solicitar reconciliação/novo shutdown.

**Resultado exigido:** Mesma identidade de recurso é contida e observada; slot liberado uma vez, sem processo substituto.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-05 — Desconexão do chamador antes da primeira fila

**Achado:** V02. **Camada:** unit. **Estado no snapshot:** NOT_RUN.

**Preparação:** Tentativa registrada, unidade ainda não começou e nenhum spawn ocorreu.

**Ação:** Cancelar waiter e executar shutdown antes de liberar worker.

**Resultado exigido:** Recusa comprovada sem efeito, reserva finalizada com prova; não criar unknown artificial permanente.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-06 — Efeito já iniciado antes de cancelamento

**Achado:** V02. **Camada:** fault injection + processo de laboratório. **Estado no snapshot:** NOT_RUN.

**Preparação:** Spawn passou; retorno/handshake atrasado.

**Ação:** Cancelar waiter e invalidar autorização.

**Resultado exigido:** Producer observado independentemente; árvore própria contida; jamais not_sent global depois do spawn.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-07 — Observe travado não bloqueia força tardia

**Achado:** V02. **Camada:** fault injection. **Estado no snapshot:** NOT_RUN.

**Preparação:** Handle tardio com observação retida.

**Ação:** Vencer orçamento e pedir contenção.

**Resultado exigido:** Força independente de observe, sem consumir workers críticos com polling ilimitado.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-08 — Storage falha na liberação de slot

**Achado:** V02. **Camada:** fault injection. **Estado no snapshot:** NOT_RUN.

**Preparação:** Parada real observada; persistência de liberação indisponível.

**Ação:** Finalizar tentativa e chamar shutdown novamente.

**Resultado exigido:** Não mentir sobre commit; obrigação durável rastreada e finalizada após recuperação, sem novo kill alheio.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-09 — Nova geração e callback antigo

**Achado:** V02. **Camada:** unit. **Estado no snapshot:** NOT_RUN.

**Preparação:** Registro atual possui identidade/geração diferente da tentativa que termina.

**Ação:** Entregar handle antigo e tentar transferência de ownership.

**Resultado exigido:** Não matar sessão nova nem abandonar recurso antigo próprio; comparar scope, geração e birth/handle.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-10 — Disposal repetido e resultado incerto

**Achado:** V02. **Camada:** contract + wheel. **Estado no snapshot:** NOT_RUN.

**Preparação:** Factory interna; produtores e forças pendentes em combinações diferentes.

**Ação:** Executar shutdown duas vezes, primeiro parcial depois resolvido.

**Resultado exigido:** Pool crítico permanece vivo enquanto necessário e é descartado publicamente ao fim, sem import privado.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-02-11 — Capacidade de aberturas canceladas

**Achado:** V02. **Camada:** load controlado. **Estado no snapshot:** NOT_RUN.

**Preparação:** Várias tentativas até o limite, cancelando seus waiters.

**Ação:** Tentar mais opens e completar resultados antigos em ordem variada.

**Resultado exigido:** Sem contornar limite por remover waiter; recursos/tarefas limitados; sem dupla liberação.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-03-01 — Accept recusado antes de bytes não consome o pedido

**Achado:** V03. **Camada:** transport real + stdin de laboratório. **Estado no snapshot:** FAIL.

**Preparação:** Pedido Codex válido; accept retido no write lock.

**Ação:** Vencer lease, liberar lock e provar zero bytes; enviar decline para o mesmo pedido.

**Resultado exigido:** Primeira recusa preserva pedido recuperável; decline produz negativa correta.

**Evidência:** regressoes/test_c6_review.py::test_v03_prewrite_refused_accept_can_still_be_declined

## AC6-03-02 — Duas decisões concorrentes e uma reserva

**Achado:** V03. **Camada:** unit + transport. **Estado no snapshot:** NOT_RUN.

**Preparação:** Mesmo request_id/hash/turno e duas tentativas com token distinto.

**Ação:** Concorrer accept/deny; atrasar uma escrita.

**Resultado exigido:** No máximo uma resposta efetiva; tentativa antiga não desfaz reserva nova.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-03-03 — Write parcial ou flush com resultado incerto

**Achado:** V03. **Camada:** transport controlado. **Estado no snapshot:** NOT_RUN.

**Preparação:** Writer conta bytes antes de levantar erro.

**Ação:** Responder aprovação e repetir pedido.

**Resultado exigido:** Não restaurar PENDING após possível efeito nem enviar segunda resposta cegamente.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-03-04 — Pedido substituído enquanto writer aguarda

**Achado:** V03. **Camada:** unit + transport. **Estado no snapshot:** NOT_RUN.

**Preparação:** Pedido antigo reservado; turno/request é substituído.

**Ação:** Recusar guarda e executar rollback de reserva.

**Resultado exigido:** Não ressuscitar pedido encerrado nem responder ao turno novo.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-03-05 — Runtime, receipt e pending_native_requests coerentes

**Achado:** V03. **Camada:** integração interna. **Estado no snapshot:** NOT_RUN.

**Preparação:** Pedido recebido pelo pump; resposta via API pública.

**Ação:** Causar recusa pré-byte e depois negativa válida.

**Resultado exigido:** Memória do adapter, Core e recibo distinguem reservado, não enviado e enviado; sem pendência fantasma.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-03-06 — Input e elicitation

**Achado:** V03. **Camada:** transport + schema. **Estado no snapshot:** NOT_RUN.

**Preparação:** Pedidos nativos de input/elicitation suportados.

**Ação:** Recusar antes do byte, negar corretamente, testar payload inválido.

**Resultado exigido:** Sem consumo por simples validação rejeitada; nenhum conteúdo sensível em erro.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-03-07 — Rotas Claude equivalentes

**Achado:** V03. **Camada:** adapter controlado. **Estado no snapshot:** NOT_RUN.

**Preparação:** Método de autorização Claude realmente suportado e ativo.

**Ação:** Aplicar barreira pós-reserva com recusa comprovadamente pré-efeito.

**Resultado exigido:** Sem reprodução do consumo prematuro; capacidade ausente permanece indisponível e documentada.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-03-08 — Tokens de reserva sob cancelamento e timeout

**Achado:** V03. **Camada:** unit. **Estado no snapshot:** NOT_RUN.

**Preparação:** Writer reservado, tarefa de resposta cancelada/expirada em fronteiras diferentes.

**Ação:** Observar término tardio da unidade nativa.

**Resultado exigido:** Resultado do waiter não determina resultado da escrita; liberar ou preservar reserva com prova.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-04-01 — Limite incremental cap+1

**Achado:** M01. **Camada:** scanner real. **Estado no snapshot:** FAIL.

**Preparação:** Mil arquivos, orçamento reduzido a quatro.

**Ação:** Enumerar até recusar, contando nomes realmente obtidos.

**Resultado exigido:** Ler no máximo cinco; não trocar algoritmo incremental por materialização global.

**Evidência:** regressoes/test_review5_original.py::test_u07_directory_scan_enforces_budget_during_enumeration

## AC6-04-02 — Layouts dentro do orçamento continuam válidos

**Achado:** M01. **Camada:** unit. **Estado no snapshot:** NOT_RUN.

**Preparação:** Diretório com zero, cap-1 e cap arquivos; links conforme política.

**Ação:** Construir seal/digest e comparar com conteúdo igual em outra raiz.

**Resultado exigido:** Não rejeitar layout válido nem mudar semântica de hash por corrigir limite.

**Evidência:** Não executado nesta auditoria; implementar ou vincular teste que demonstre a condição causal.

## AC6-04-03 — Controle positivo da guarda de turno normal

**Achado:** validação transversal. **Camada:** transport real. **Estado no snapshot:** PASS.

**Preparação:** Original C5 inclui contador de escrita.

**Ação:** Executar controle send_turn no writer real após espera.

**Resultado exigido:** Proteção já entregue continua passando.

**Evidência:** regressoes/test_review5_original.py::test_control_c4_guarded_turn_refuses_after_real_write_lock

## AC6-04-04 — Regressões históricas C2–C5 entregues

**Achado:** validação transversal. **Camada:** regressão. **Estado no snapshot:** PASS.

**Preparação:** Ambiente e snapshot identificados.

**Ação:** Executar arquivos históricos e test_c5_audit entregues.

**Resultado exigido:** Preservar causalidade e classificar o skip/warning; não somar subconjuntos como testes distintos.

**Evidência:** evidencias/historical.xml; evidencias/c5_delivered.xml

## AC6-04-05 — Wheel/sdist e import externo

**Achado:** validação transversal. **Camada:** empacotamento. **Estado no snapshot:** PASS.

**Preparação:** Build isolado, wheel instalado fora da árvore.

**Ação:** Importar API e recursos com python -I.

**Resultado exigido:** Artefato instalável, sem imports acidentais da fonte.

**Evidência:** evidencias/build.json; evidencias/installed_import.log

## AC6-04-06 — Contrato NXL sem promoção artificial

**Achado:** validação transversal. **Camada:** contract. **Estado no snapshot:** PASS.

**Preparação:** Bundle do wheel instalado.

**Ação:** Verificar bundle aceitando development-partial explicitamente.

**Resultado exigido:** Schemas/arquivos íntegros; não declarar E2 por passar esta verificação.

**Evidência:** evidencias/installed_bundle.log

## AC6-04-07 — Qualificação real de backend no SO-alvo

**Achado:** validação transversal. **Camada:** plataforma/provider. **Estado no snapshot:** BLOCKED.

**Preparação:** Host com contenção real qualificada, ambiente registrado.

**Ação:** Executar campanha no backend e providers anunciados, incluindo árvore controlada; registrar limitações.

**Resultado exigido:** Sem ignorar gates; evidência de Windows/WSL2 do executor não confundida com reprodução nesta auditoria.

**Evidência:** Este sandbox não disponibiliza proc_children; providers reais não executados.

## AC6-04-08 — Consumidores instalados sintéticos

**Achado:** validação transversal. **Camada:** contract de consumidores. **Estado no snapshot:** PASS.

**Preparação:** Mesmo wheel em alvo externo.

**Ação:** Executar embedded_consumer e remote_consumer de laboratório.

**Resultado exigido:** Ambos usam artefato; resultado não equivale aos produtos Server/Connector em dois hosts.

**Evidência:** evidencias/embedded.log; evidencias/remote.log
