# Matriz de aceite C8

24 cenários: três FAIL, dois controles PASS, dezoito NOT_RUN e um BLOCKED. Os cinco resultados novos executados não são somados a campanhas históricas. Os demais descrevem critérios de validação do código a corrigir.

## AC8-01-01 — Linha de conexão mais nova já observada

**Fase:** C8-01. **Estado na auditoria:** FAIL.

**Preparação:** Contexto 3; sessão aberta; duas conexões SQLite reais.

**Ação:** Peer avança para 5; renew propõe 4/expected 3; conferir erro no estágio lease_cas; enviar trabalho pelo contexto 3.

**Resultado exigido:** Zero send_turn e recusa tipada; não instalar permissões a partir da linha.

**Evidência:** test_x01_observed_newer_durable_fence_blocks_old_context; validated_new.xml e validated_repeat.xml

## AC8-01-02 — Controle: renew normal

**Fase:** C8-01. **Estado na auditoria:** PASS.

**Preparação:** Mesma API, sem peer avançando a linha.

**Ação:** Renovar com contexto seguinte válido e enviar tarefa explicitamente solicitada.

**Resultado exigido:** Uma tarefa SUBMITTED, sem falso bloqueio.

**Evidência:** test_control_normal_renewal_still_allows_authorized_work; validated_new.xml e validated_repeat.xml

## AC8-01-03 — Falha segura e linha antiga

**Fase:** C8-01. **Estado na auditoria:** NOT_RUN.

**Preparação:** Produtor recusado antes da entrega; primeira leitura indisponível.

**Ação:** Restaurar leitura da linha anterior exata; usar classificador corrigido.

**Resultado exigido:** Finalizar só tentativa; novo submit explícito funciona; não repetir CAS.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-01-04 — Avanço de owner, autorização e configuração

**Fase:** C8-01. **Estado na auditoria:** NOT_RUN.

**Preparação:** Parametrizar componente durável que avança, com conexão/scopes válidos.

**Ação:** Produzir conflito real e tentar concessão pelo contexto anterior.

**Resultado exigido:** Nenhum contexto superado permanece produtivo; erro estável e controle seguro disponíveis.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-01-05 — Commit confirmado e ACK perdido

**Fase:** C8-01. **Estado na auditoria:** NOT_RUN.

**Preparação:** CAS real que comita revogação ou renew; wrapper perde confirmação.

**Ação:** Reconciliação por leitura consistente, inclusive com indisponibilidade inicial.

**Resultado exigido:** Revogação restringe; renew só aplica proposta autorizada exata e binding compatível; sem confundir término com rollback.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-01-06 — Linha ausente ou resultado não conclusivo

**Fase:** C8-01. **Estado na auditoria:** NOT_RUN.

**Preparação:** Tentativa com prova de entrega incerta ou linha inesperadamente ausente.

**Ação:** Finalizar/reconciliar sem prova de falha segura.

**Resultado exigido:** Conserva fence e recuperação explícita; não concede somente por terminar o Future.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-01-07 — Callback de tentativa velha

**Fase:** C8-01. **Estado na auditoria:** NOT_RUN.

**Preparação:** Barreira retém leitura de finalizador; uma transição posterior torna contexto inválido.

**Ação:** Liberar callback antigo após mudança de token/revisão/shutdown.

**Resultado exigido:** Não limpa hold nem aplica contexto da tentativa nova; compara token após await.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-01-08 — Idempotência e controles durante fence

**Fase:** C8-01. **Estado na auditoria:** NOT_RUN.

**Preparação:** Recibo conhecido e sessão com generation fence fechado.

**Ação:** Repetir mesma operação conhecida, tentar tarefa nova, negar pedido válido e solicitar contenção.

**Resultado exigido:** Recibo sem novo efeito; tarefa produtiva recusada; controles seguros preservados no escopo autorizado.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-02-01 — Falha de release após STOPPED

**Fase:** C8-02. **Estado na auditoria:** FAIL.

**Preparação:** Open cancelado retorna peer tardio; parada comprovada; SQLite real.

**Ação:** Recusar uma liberação antes do commit; restaurar storage e chamar shutdown duas vezes.

**Resultado exigido:** Reserva liberada com confirmação, ou obrigação ainda explicitamente recuperável até a confirmação; nunca apagada silenciosamente.

**Evidência:** test_x02_late_stop_keeps_failed_slot_release_recoverable; validated_new.xml e validated_repeat.xml

## AC8-02-02 — Controle: release com ledger disponível

**Fase:** C8-02. **Estado na auditoria:** PASS.

**Preparação:** Mesmo retorno tardio sem falha no ledger.

**Ação:** Encerrar e consultar owned_slot_page.

**Resultado exigido:** Zero reservas após STOPPED e commit; sem retenção artificial.

**Evidência:** test_control_late_stop_with_available_ledger_releases_slot; validated_new.xml e validated_repeat.xml

## AC8-02-03 — Release com confirmação perdida

**Fase:** C8-02. **Estado na auditoria:** NOT_RUN.

**Preparação:** Ledger confirma release real e perde ACK.

**Ação:** Retomar pelo lifecycle público; consultar chave exata.

**Resultado exigido:** Converge idempotentemente sem duplicar semântica, erro fictício ou liberar outra reserva.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-02-04 — Falha persistente sem relatório vazio

**Fase:** C8-02. **Estado na auditoria:** NOT_RUN.

**Preparação:** STOPPED observado e release indisponível por toda a campanha.

**Ação:** Encerrar com orçamento curto e consultar resultado público.

**Resultado exigido:** Informa pendência durável; não omite tudo como resolvido; retry limitado e nenhum novo kill/spawn.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-02-05 — Reabertura do ledger

**Fase:** C8-02. **Estado na auditoria:** NOT_RUN.

**Preparação:** Ledger com reserva original e obrigação de release; backend encerrado/reaberto em teste.

**Ação:** Retomar obrigação quando a prova de parada/ownership ainda é válida; simular ausência dessa prova em variante.

**Resultado exigido:** Com prova, release exato; sem prova, unknown conservador e nenhuma inferência por PID; não apagar história.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-02-06 — Finalização concorrente e disposal

**Fase:** C8-02. **Estado na auditoria:** NOT_RUN.

**Preparação:** Dois waiters aguardam a mesma obrigação de release.

**Ação:** Completar commit e encerrar consumidores.

**Resultado exigido:** Uma finalização lógica; relatório convergente; descarta apenas pools não utilizados; nenhum import privado exigido.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-03-01 — Força física duplicada por shutdown

**Fase:** C8-03. **Estado na auditoria:** FAIL.

**Preparação:** Peer executa força síncrona bloqueada numa thread; open waiter cancelado.

**Ação:** Com primeiro worker ainda ativo, executar shutdown e deixar expirar orçamento de espera.

**Resultado exigido:** No máximo uma unidade física em voo para a mesma força/handle; segundo waiter reutiliza.

**Evidência:** test_x03_repeat_shutdown_coalesces_physical_force_in_flight; validated_new.xml e validated_repeat.xml

## AC8-03-02 — Retry legítimo após falha concluída

**Fase:** C8-03. **Estado na auditoria:** NOT_RUN.

**Preparação:** Primeira unidade física retorna falha/unknown e terminou realmente.

**Ação:** Backend volta; nova solicitação pública sobre mesmo recurso.

**Resultado exigido:** Segunda unidade permitida sem sobreposição; atinge STOPPED se backend comprovar; nenhum novo spawn.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-03-03 — Close lento, inclusive ao cancelar

**Fase:** C8-03. **Estado na auditoria:** NOT_RUN.

**Preparação:** Close observa cancelamento e aguarda seu backend.

**Ação:** Expirar prazo da contenção enquanto close continua retido.

**Resultado exigido:** Força começa independentemente; preservar sementes W03 originais contra implementação alterada.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-03-04 — Waiters cancelados repetidamente

**Fase:** C8-03. **Estado na auditoria:** NOT_RUN.

**Preparação:** Unidade física começou; vários chamadores pedem shutdown e deixam de aguardar.

**Ação:** Cancelar waiters antes/depois de timeout sem liberar worker.

**Resultado exigido:** Produtor físico retido; sem despacho duplicado nem Task exception não observada; recuperação continua pública.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-03-05 — Limites entre recursos distintos

**Fase:** C8-03. **Estado na auditoria:** NOT_RUN.

**Preparação:** Vários handles, um com força travada e outros respondendo; pools limitados.

**Ação:** Flood limitado de chamadas repetidas em cada recurso.

**Resultado exigido:** Por recurso coalescido, limites globais obedecidos e outros recursos não bloqueados por lock global; backpressure explícito.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-03-06 — Storage e observer indisponíveis

**Fase:** C8-03. **Estado na auditoria:** NOT_RUN.

**Preparação:** Força com journal/observer bloqueados, handle registrado.

**Ação:** Pedir contenção e aguardar entrada física antes de liberar os bloqueios.

**Resultado exigido:** Força independente; sem inferir parada nem commit; retry mantém mesma unidade em voo.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-04-01 — Regressões históricas após a correção

**Fase:** C8-04. **Estado na auditoria:** NOT_RUN.

**Preparação:** Versão final a ser produzida pelo executor, matriz C2–C7.

**Ação:** Executar sementes originais/reconstruídas e suite no SO disponível.

**Resultado exigido:** Preserva correções; registra resultados por campanha sem somar sobreposições. Os PASS da auditoria são baseline, não prova do futuro diff.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-04-02 — Wheel e consumidores após a correção

**Fase:** C8-04. **Estado na auditoria:** NOT_RUN.

**Preparação:** Wheel/sdist finais, ambiente fora do repo.

**Ação:** Instalar e testar API/erros/estado de recuperação com -I e bundle hash fixado.

**Resultado exigido:** Mesmo artefato nos consumidores; nenhuma dependência de internals; synthetic não prova hosts reais.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.

## AC8-04-03 — Backend de processo real

**Fase:** C8-04. **Estado na auditoria:** BLOCKED.

**Preparação:** SO com backend de contenção disponível, processo de laboratório inofensivo.

**Ação:** Qualificar cancelamento tardio, chamadas repetidas, nascimento/ownership e parada.

**Resultado exigido:** Comprovar unidades físicas e STOPPED; nunca atingir processo externo.

**Evidência:** Não executado: sandbox desta auditoria não disponibiliza proc_children exigido; não desativar gate.

## AC8-04-04 — MCP HTTP direto e identidade preservados

**Fase:** C8-04. **Estado na auditoria:** NOT_RUN.

**Preparação:** Diff final e consumers qualificados quando disponíveis.

**Ação:** Inspecionar dependências/entrypoints e provar que nenhuma mudança cria proxy MCP ou nova identidade.

**Resultado exigido:** Core segue biblioteca de runtime; Server mantém autoridade; não altera transporte remoto por efeito colateral.

**Evidência:** Não executado nesta auditoria; implementar/relacionar teste equivalente.
