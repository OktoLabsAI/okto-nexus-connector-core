# Matriz de aceite C7

Estados refletem exclusivamente esta revisão. PASS não significa provider real salvo indicação explícita. Cenários podem compartilhar testes.

## AC7-00-01 — Integridade do snapshot

**Estado:** PASS · **Fase:** C7-00

**Preparação:** ZIP original e diretório extraído.

**Ação:** Conferir comentário de commit e hash de cada arquivo original.

**Resultado exigido:** Baseline identificada; nenhuma alteração nos 366 arquivos originais.

**Evidência:** evidencias/source_manifest.json

## AC7-00-02 — Dependências autênticas

**Estado:** PASS · **Fase:** C7-00

**Preparação:** rfc8785 ausente no ambiente; rede PyPI indisponível.

**Ação:** Recuperar dois arquivos upstream 0.1.4 e comparar Git blob SHA; testar imports isolados.

**Resultado exigido:** Sem stub/implementação substituta e sem diagnosticar erro de setup como defeito.

**Evidência:** evidencias/environment.json; isolated_import_final.log

## AC7-01-01 — Close demora a terminar cancelamento

**Estado:** FAIL · **Fase:** C7-01

**Preparação:** Abertura cancelada, producer devolve handle; close cooperativo aguarda recurso.

**Ação:** Fazer shutdown zero; close observa cancelamento mas continua aguardando.

**Resultado exigido:** Força é despachada sem terminar close nem o seu cancelamento.

**Evidência:** test_c7_review.py::test_w03_force_does_not_wait_for_close_cancellation_to_finish

## AC7-01-02 — Observer bloqueado e segunda recuperação

**Estado:** FAIL · **Fase:** C7-01

**Preparação:** Primeira força falha temporariamente; observe aguarda.

**Ação:** Shutdown esgota espera; restaurar observer e repetir shutdown.

**Resultado exigido:** Segunda força alcança o mesmo handle, sem novo spawn.

**Evidência:** test_c7_review.py::test_w03b_second_shutdown_can_retry_late_handle_after_observer_stalls

## AC7-01-03 — Retenção simples de handle não encerrado

**Estado:** PASS · **Fase:** C7-01

**Preparação:** Força falha e observe retorna RUNNING sem travar.

**Ação:** Retirar referências da fixture, coletar lixo.

**Resultado exigido:** Core conserva handle enquanto STOPPED não foi observado.

**Evidência:** test_c6_original_adaptado.py::test_v02b_unconfirmed_late_handle_remains_owned_for_recovery; fixture_c6.diff

## AC7-01-04 — Persistência após STOPPED

**Estado:** NOT_RUN · **Fase:** C7-01

**Preparação:** Parada comprovada; release_owned_slot falha.

**Ação:** Recuperar o journal e repetir lifecycle público.

**Resultado exigido:** Obrigação de liberação permanece identificada até o commit; nenhum pool necessário descartado.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-01-05 — Duas chamadas concorrentes de shutdown

**Estado:** NOT_RUN · **Fase:** C7-01

**Preparação:** Mesmo handle em OWNED_UNKNOWN.

**Ação:** Repetir shutdown em paralelo e com prazos menores.

**Resultado exigido:** Controles coalescidos, menor deadline preservado; nada executado sobre outro owner.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-01-06 — Journal bloqueado na adoção tardia

**Estado:** NOT_RUN · **Fase:** C7-01

**Preparação:** Handle retornado; storage retido.

**Ação:** Iniciar close/force e manter storage bloqueado.

**Resultado exigido:** Propriedade registrada em memória e despacho da força não dependem do armazenamento.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-01-07 — Cancelamentos sucessivos

**Estado:** NOT_RUN · **Fase:** C7-01

**Preparação:** Waiter e shutdown cancelados em fronteiras diferentes.

**Ação:** Restaurar backend e consultar/parar via API pública.

**Resultado exigido:** Registro forte e task produtora continuam reconciliáveis; nada removido por cancelamento de waiter.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-01-08 — Backend físico qualificado

**Estado:** BLOCKED · **Fase:** C7-01

**Preparação:** SO com backend de contenção suportado; processo de laboratório.

**Ação:** Segurar handshake/close e encerrar sobre handle com birth token.

**Resultado exigido:** Despacho, propriedade e parada comprovados sem matar processo externo.

**Evidência:** Neste sandbox proc_children não está disponível; campanha física requerida em ambiente qualificado.

## AC7-02-01 — Renew falha antes da entrega e storage volta

**Estado:** FAIL · **Fase:** C7-02

**Preparação:** CAS recusado com JOURNAL_FULL antes de enfileirar; primeira leitura falha.

**Ação:** Deixar terminar toda a campanha real de reconciliação; ler linha antiga.

**Resultado exigido:** Tentativa segura converge, hold da tentativa é resolvido; novo trabalho explicitamente solicitado pode seguir.

**Evidência:** test_c7_review.py::test_w02_recovery_finishes_failed_attempt_when_old_row_is_proven[renew]

## AC7-02-02 — Revoke falha antes da entrega e storage volta

**Estado:** FAIL · **Fase:** C7-02

**Preparação:** Mesmo cenário, pedido de revogação.

**Ação:** Restauração da leitura e término do produtor comprovados.

**Resultado exigido:** Não confundir falha comprovadamente não entregue com commit ainda possível; nenhuma repetição de CAS.

**Evidência:** test_c7_review.py::test_w02_recovery_finishes_failed_attempt_when_old_row_is_proven[revoke]

## AC7-02-03 — Commit tardio com ACK perdido

**Estado:** PASS · **Fase:** C7-02

**Preparação:** Chamador cancelado; CAS comita revoke e perde confirmação.

**Ação:** Consultar durable revoked e tentar novo submit pelo contexto antigo.

**Resultado exigido:** Nenhum send produtivo.

**Evidência:** test_c6_original_adaptado.py::test_v01_uncertain_revocation_never_allows_old_work[cancel_then_lost_ack]

## AC7-02-04 — Commit sem leitura de recuperação

**Estado:** PASS · **Fase:** C7-02

**Preparação:** Revoke comitado; ACK falha; read indisponível.

**Ação:** Tentar trabalho antes de o finalizador obter prova.

**Resultado exigido:** Hold impede trabalho, sem transformar a recusa em tarefa executada.

**Evidência:** test_c6_original_adaptado.py::test_v01_uncertain_revocation_never_allows_old_work[read_unavailable_after_commit]

## AC7-02-05 — Callback de tentativa antiga

**Estado:** NOT_RUN · **Fase:** C7-02

**Preparação:** Tentativa A resolvida; B corrente em outra revisão.

**Ação:** Liberar callback atrasado de A depois de B.

**Resultado exigido:** Token capturado impede limpar ou aplicar estado da tentativa B.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-02-06 — Linha nova e confirmação antiga

**Estado:** NOT_RUN · **Fase:** C7-02

**Preparação:** Registro durável possui revisão/owner mais novo.

**Ação:** Finalizar tentativa antiga que lê a linha nova.

**Resultado exigido:** Nenhum contexto antigo aplicado; comparação completa e estado conservador.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-02-07 — Recibo conhecido durante hold

**Estado:** NOT_RUN · **Fase:** C7-02

**Preparação:** Operação já persistida; lease entra em UNKNOWN.

**Ação:** Repetir exatamente ID/hash e depois tentar operação nova.

**Resultado exigido:** Recibo conhecido permanece consultável; nova operação segue bloqueada, sem duplicação.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-02-08 — Recovery após esgotar retries sem prova

**Estado:** NOT_RUN · **Fase:** C7-02

**Preparação:** Store continua indisponível ao fim do orçamento.

**Ação:** Restaurar depois; usar gatilho público/coalescido documentado.

**Resultado exigido:** Recuperação prossegue sem alterar flags privadas; hold não é liberado por tempo.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-03-01 — Decline público após prazo

**Estado:** FAIL · **Fase:** C7-03

**Preparação:** Pedido observado e ainda válido; lease produtiva passa do prazo.

**Ação:** Chamar decide_native_approval com decline.

**Resultado exigido:** Uma resposta negativa; identidade, allowed_actions e correlação preservadas.

**Evidência:** test_c7_review.py::test_w04_public_approval_distinguishes_containment_from_new_permission[decline]

## AC7-03-02 — Cancel público após prazo

**Estado:** FAIL · **Fase:** C7-03

**Preparação:** Mesmo cenário, decisão cancel.

**Ação:** Usar API pública.

**Resultado exigido:** Resposta nativa explicitamente negativa, sem concessão de trabalho.

**Evidência:** test_c7_review.py::test_w04_public_approval_distinguishes_containment_from_new_permission[cancel]

## AC7-03-03 — Accept público após prazo continua recusado

**Estado:** PASS · **Fase:** C7-03

**Preparação:** Mesmo alvo e prazo de decline/cancel.

**Ação:** Tentar accept.

**Resultado exigido:** AGENT_REVOKED e zero respostas no peer.

**Evidência:** test_c7_review.py::test_w04_public_approval_distinguishes_containment_from_new_permission[accept]

## AC7-03-04 — Reserva recuperável no adaptador

**Estado:** PASS · **Fase:** C7-03

**Preparação:** Accept chega ao writer e vence antes do primeiro byte.

**Ação:** Recusar e depois negar o mesmo pedido pelo adaptador/bridge.

**Resultado exigido:** Zero byte no accept e uma resposta negativa posterior.

**Evidência:** test_c6_original_adaptado.py::test_v03_prewrite_refused_accept_can_still_be_declined

## AC7-03-05 — Input não vira exceção produtiva

**Estado:** NOT_RUN · **Fase:** C7-03

**Preparação:** Pedido de input com conteúdo ou erro de validação.

**Ação:** Tentar accept de input expirado e cancelar pedido com schema próprio.

**Resultado exigido:** Input não é enviado por classificação genérica de contenção; cancel só usa formato negativo suportado.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-03-06 — Outro agente, turno ou capability

**Estado:** NOT_RUN · **Fase:** C7-03

**Preparação:** Pedido válido pertence a outro scope ou perdeu correlação.

**Ação:** Tentar decline/accept sem autoridade pertinente.

**Resultado exigido:** Recusa antes do writer; exceção temporal não remove autenticação ou escopo.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-03-07 — Escrita parcial

**Estado:** NOT_RUN · **Fase:** C7-03

**Preparação:** Writer enviou bytes e falha no flush.

**Ação:** Tentar classificar e repetir operação.

**Resultado exigido:** Possível efeito/unknown preservado; não restaurar pending para resposta cega.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-04-01 — Submit de sessão nunca existente

**Estado:** FAIL · **Fase:** C7-04

**Preparação:** Contexto válido; nenhum runtime aberto.

**Ação:** Enviar TurnOperation para missing.

**Resultado exigido:** CoreError SESSION_UNKNOWN; zero send.

**Evidência:** test_c7_review.py::test_w01_unknown_session_returns_typed_error[submit]

## AC7-04-02 — Steer de sessão nunca existente

**Estado:** FAIL · **Fase:** C7-04

**Preparação:** Contexto com capability steer; nenhuma sessão.

**Ação:** Enviar controle steer com alvo sintático válido.

**Resultado exigido:** CoreError SESSION_UNKNOWN; zero efeito.

**Evidência:** test_c7_review.py::test_w01_unknown_session_returns_typed_error[steer]

## AC7-04-03 — Recibo depois de evicção

**Estado:** NOT_RUN · **Fase:** C7-04

**Preparação:** Operação persistida; sessão fechada e retirada do registro.

**Ação:** Repetir ID/hash e depois mesmo ID com outro hash.

**Resultado exigido:** Recibo original e conflito tipado; não exigir sessão viva para replay.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-04-04 — Não ocultar erro de autorização

**Estado:** NOT_RUN · **Fase:** C7-04

**Preparação:** Sessão real de outro agente.

**Ação:** Enviar submit/steer por contexto incorreto.

**Resultado exigido:** BINDING_NOT_AUTHORIZED ou contrato equivalente já documentado; nunca criar sessão para contornar.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-04-05 — Draining e sessão ausente

**Estado:** NOT_RUN · **Fase:** C7-04

**Preparação:** Shutdown iniciado, ID ausente.

**Ação:** Enviar nova operação.

**Resultado exigido:** Erro tipado consistente com precedência documentada; sem AttributeError.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-05-01 — Histórico preservado

**Estado:** PASS · **Fase:** C7-05

**Preparação:** Arquivos C2/C3/C4 do snapshot mais originais C5.

**Ação:** Rodar sem remover guardas.

**Resultado exigido:** 44 PASS e 1 SKIP no subconjunto histórico; C5 original 11 PASS, contagens não aditivas à suíte completa.

**Evidência:** evidencias/c6_original_runner/summary.json

## AC7-05-02 — Build e importação instalada

**Estado:** PASS · **Fase:** C7-05

**Preparação:** Backend setuptools, cópia separada e ambiente auditado.

**Ação:** Gerar wheel/sdist, instalar wheel fora da árvore e importar com -I.

**Resultado exigido:** Artefato importável; dependências reais verificadas.

**Evidência:** evidencias/build_metadata.json; isolated_import_final.log

## AC7-05-03 — Bundle com status explícito

**Estado:** PASS · **Fase:** C7-05

**Preparação:** Manifesto sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630.

**Ação:** Verificar bundle instalado com opt-in development-partial.

**Resultado exigido:** Schemas/fixtures/vetores válidos; não alegar status normativo.

**Evidência:** evidencias/bundle.log

## AC7-05-04 — Consumidores sintéticos

**Estado:** PASS · **Fase:** C7-05

**Preparação:** Mesmo wheel instalado.

**Ação:** Executar exemplos embedded_consumer e remote_consumer fora do checkout.

**Resultado exigido:** Ambos terminam OK; isto não demonstra dois hosts reais.

**Evidência:** evidencias/embedded.log; remote.log

## AC7-05-05 — Providers reais

**Estado:** NOT_RUN · **Fase:** C7-05

**Preparação:** Versões/SOs explicitamente qualificados, credenciais fornecidas em ambiente adequado.

**Ação:** Campanha de cada capability anunciada.

**Resultado exigido:** Evidência de provider separada de peers sintéticos; sem cobrança/configuração por inferência.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.

## AC7-05-06 — Integração dos dois produtos

**Estado:** NOT_RUN · **Fase:** C7-05

**Preparação:** Server e Connector reais em hosts distintos, mesmo wheel.

**Ação:** Executar local sem Connector e remoto com recuperação, MCP HTTP direto.

**Resultado exigido:** Gate E2 apenas com evidência própria dos consumidores.

**Evidência:** Não executado nesta revisão; registrar evidência na implementação.
