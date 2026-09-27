# Matriz C4 — cenários de aceite

Os dez primeiros casos foram executados nesta auditoria e falharam em `8677145`. Os demais são cenários complementares exigidos pelo plano; estão `NOT_RUN` nesta auditoria. Isso **não significa** que não existam testes parciais no repositório: o agente deve mapear e executar o cenário exato antes de atribuir PASS.

A expectativa das sementes Node admite uma alternativa de produto: recusa explícita e segura de layout realmente não suportado. O teste atual exige alteração do digest porque a versão atual aceita o layout; caso a correção escolha a recusa, adapte a fixture com justificativa e prova de que não houve qualificação. Não substitua por skip.

Cada cenário precisa de: task/commit, ambiente, comando/node pytest, logs/XML, hash do wheel, resultado real e limitações. Dez parametrizações não equivalem a dez grupos independentes de achados. Nenhuma repetição de execução é somada à contagem de cenários.

## C4T-01 · T01 · C4-01

**Camada:** fault injection Core+journal. **Estado na auditoria:** `FAIL`.

**Preparação:** Sessão própria; close retido; journal.admit da força bloqueado por Event.

**Ação:** Iniciar shutdown com orçamento curto e manter storage preso.

**Obrigatório observar:** Função física de força começa sem liberar storage; resultado de parada/persistência continua honesto.

**Semente:** `test_t01_emergency_force_does_not_wait_for_journal_admission` em `regressoes/test_review4.py`.

## C4T-02 · T02 · C4-04

**Camada:** fault injection Core+journal. **Estado na auditoria:** `FAIL`.

**Preparação:** CAS renew falha comprovadamente antes de entrega.

**Ação:** Restaurar journal e repetir renewal válido.

**Obrigatório observar:** Sem RECONNECT_BUSY permanente; tentativa anterior finalizada.

**Semente:** `test_t02_cas_failure_does_not_poison_future_lease_operations[renew]` em `regressoes/test_review4.py`.

## C4T-03 · T02 · C4-04

**Camada:** fault injection Core+journal. **Estado na auditoria:** `FAIL`.

**Preparação:** CAS revoke falha comprovadamente antes de entrega.

**Ação:** Restaurar journal e repetir revogação válida.

**Obrigatório observar:** Sem REVOKE_BUSY permanente; revogação efetivamente aplicada.

**Semente:** `test_t02_cas_failure_does_not_poison_future_lease_operations[revoke]` em `regressoes/test_review4.py`.

## C4T-04 · T03 · C4-02

**Camada:** bridge + adapter Codex + transporte real / stdin de laboratório. **Estado na auditoria:** `FAIL`.

**Preparação:** Clock inicialmente válido; lock nativo retido; comando já passou pela bridge.

**Ação:** Vencer prazo durante acquire do lock e liberar.

**Obrigatório observar:** Nenhum byte de turn/start gravado; recusa antes do efeito.

**Semente:** `test_t03_deadline_rechecked_after_real_codex_transport_write_lock` em `regressoes/test_review4.py`.

## C4T-05 · T04 · C4-03

**Camada:** composição pública+factory+kernel / peer de laboratório. **Estado na auditoria:** `FAIL`.

**Preparação:** Open aguarda environment, ainda sem Session, com recursos da factory.

**Ação:** shutdown(0,0).

**Obrigatório observar:** Pools não descartados enquanto abertura puder produzir efeito.

**Semente:** `test_t04_shutdown_retains_executors_while_native_open_is_pending` em `regressoes/test_review4.py`.

## C4T-06 · T04 · C4-03

**Camada:** composição pública+factory+kernel / peer de laboratório. **Estado na auditoria:** `FAIL`.

**Preparação:** Open aguarda callback autorizado; shutdown começa/retorna.

**Ação:** Liberar callback depois.

**Obrigatório observar:** start não é alcançado; draining propaga até spawn.

**Semente:** `test_t04b_shutdown_fences_pending_environment_before_spawn` em `regressoes/test_review4.py`.

## C4T-07 · T05 · C4-03

**Camada:** composição pública+factory+kernel / peer de laboratório. **Estado na auditoria:** `FAIL`.

**Preparação:** Prepared validado; binário é modificado no callback environment.

**Ação:** Prosseguir open.

**Obrigatório observar:** Recusa de drift antes de start; não reaprovar automaticamente.

**Semente:** `test_t05_launch_rechecks_build_after_environment_callback` em `regressoes/test_review4.py`.

## C4T-08 · T06 · C4-05

**Camada:** Node real com pacote sintético, não Pi/provider. **Estado na auditoria:** `FAIL`.

**Preparação:** optionalDependency instalada/hoisted e carregada pelo entrypoint.

**Ação:** Trocar código helper v1→v2 e executar Node.

**Obrigatório observar:** Saída muda; identidade também muda ou layout é recusado explicitamente sem qualificação falsa.

**Semente:** `test_t06_present_production_dependencies_are_covered[optionalDependencies]` em `regressoes/test_review4.py`.

## C4T-09 · T06 · C4-05

**Camada:** Node real com pacote sintético, não Pi/provider. **Estado na auditoria:** `FAIL`.

**Preparação:** peerDependency presente e carregada pelo entrypoint.

**Ação:** Trocar código helper v1→v2 e executar Node.

**Obrigatório observar:** Mesmo requisito de cobertura; ausência de digest parcial válido.

**Semente:** `test_t06_present_production_dependencies_are_covered[peerDependencies]` em `regressoes/test_review4.py`.

## C4T-10 · T07 · C4-06

**Camada:** unitário função real. **Estado na auditoria:** `FAIL`.

**Preparação:** Orçamento32 bytes; único arquivo64 bytes.

**Ação:** Calcular identidade.

**Obrigatório observar:** Recusar por limite antes de hash integral do arquivo.

**Semente:** `test_t07_manifest_byte_budget_checked_before_reading_last_file` em `regressoes/test_review4.py`.

## C4T-11 · T01 · C4-01

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Lease expira com journal fora de serviço.

**Ação:** Manter bloqueio além da tolerância.

**Obrigatório observar:** Contenção entra sem depender de gravação; nenhum receipt falso.

## C4T-12 · T01 · C4-01

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Close explícito travado; persistência lenta.

**Ação:** Atingir prazo de escalada.

**Obrigatório observar:** Mesma independência de shutdown e lease.

## C4T-13 · T01 · C4-01

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Força agendada com prazo distante.

**Ação:** Novo shutdown zero antes do despacho.

**Obrigatório observar:** Prazo menor é respeitado; não aguarda tarefa velha dormir.

## C4T-14 · T01 · C4-01

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Força já emitida e sem parada observada.

**Ação:** Solicitar força repetidas vezes.

**Obrigatório observar:** Coalescência limitada; sem pool/fila ilimitada e sem repetir trabalho do agente.

## C4T-15 · T01 · C4-01

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Resposta do backend chega; record_receipt falha.

**Ação:** Consultar estado e recuperar storage.

**Obrigatório observar:** Stop observado e commit são fatos separados; reapresentação coerente.

## C4T-16 · T01 · C4-01

**Camada:** backend SO. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Processo laboratório cria filho; envio e journal travados.

**Ação:** Encerrar com força pelo caminho público.

**Obrigatório observar:** Backend físico atinge somente árvore própria; evidência de ownership registrada.

## C4T-17 · T01 · C4-01

**Camada:** backend SO. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Sessão attach externa com processo controle.

**Ação:** Shutdown/força solicitada no host.

**Obrigatório observar:** Detach não mata árvore alheia.

## C4T-18 · T03 · C4-02

**Camada:** adapter real/peer. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Pi ou Claude aguarda própria trava de escrita.

**Ação:** Prazo vence antes de primeira escrita.

**Obrigatório observar:** Recusa tardia funciona em cada adapter; teste Codex não é substituto.

## C4T-19 · T03 · C4-02

**Camada:** adapter real/peer. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Approval accept ou input permissivo aguarda lock.

**Ação:** Mudar geração/turno/pedido ou vencer prazo.

**Obrigatório observar:** Não grava autorização antiga no novo turno.

## C4T-20 · T03 · C4-02

**Camada:** adapter real/peer. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Lease vencida, alvo/ownership ainda válido.

**Ação:** Enviar deny/cancel/interrupt.

**Obrigatório observar:** Ação de contenção permitida sem abrir novo trabalho.

## C4T-21 · T03 · C4-02

**Camada:** adapter real/peer. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Um write já enviou parte dos bytes.

**Ação:** Falhar no restante/flush e repetir mesmo ID.

**Obrigatório observar:** OUTCOME_UNKNOWN; não classifica not_sent nem faz segundo efeito.

## C4T-22 · T03 · C4-02

**Camada:** concorrência. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Dois pedidos de sessões diferentes com guards diferentes.

**Ação:** Alternar espera de lock e revogar só um.

**Obrigatório observar:** Um guard não sobrescreve o outro; somente pedido válido pode escrever.

## C4T-23 · T03 · C4-02

**Camada:** integração kernel. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Guard recusa antes de qualquer write depois de mark_possible_effect.

**Ação:** Consultar/repetir recibo.

**Obrigatório observar:** Registro seguro coerente e sem nova execução.

## C4T-24 · T03 · C4-02

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Thread de dados saturada e guard fechado.

**Ação:** Disparar força e depois liberar dados.

**Obrigatório observar:** Força independente; dados tardios recusados.

## C4T-25 · T04 · C4-03

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Opening enfileirado ainda não executa.

**Ação:** Cancelar await e iniciar shutdown.

**Obrigatório observar:** Unidade tardia não dá spawn; registry não perde a tentativa.

## C4T-26 · T04 · C4-03

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Spawn pode ter ocorrido antes de cancelar, handle chega tarde.

**Ação:** Shutdown retorna orçamento esgotado e depois handle aparece.

**Obrigatório observar:** Unknown com slot preservado; contenção do handle próprio quando chega.

## C4T-27 · T04 · C4-03

**Camada:** lifecycle público. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Sem sessões/openings/forças/cleanup/CAS pendentes.

**Ação:** Chamar shutdown duas vezes.

**Obrigatório observar:** Disposal idempotente; nenhum pool interno remanescente indevido.

## C4T-28 · T04 · C4-03

**Camada:** lifecycle público. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Ownership desconhecido ainda exige controle.

**Ação:** Shutdown e final disposal.

**Obrigatório observar:** Não encerra capacidade indispensável; relatório parcial explícito.

## C4T-29 · T05 · C4-03

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Build muda depois do callback enquanto start está enfileirado.

**Ação:** Liberar worker.

**Obrigatório observar:** Recusa drift no limite efetivo, não só na saída do callback.

## C4T-30 · T05 · C4-03

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Node/script/root/refs de config mudam separadamente depois do prepare.

**Ação:** Tentar iniciar sem novo prepare/escopo.

**Obrigatório observar:** Mudança detectada; erros prescritivos, sem reaprovação silenciosa.

## C4T-31 · T04,T05 · C4-03

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Hash/verify de arquivos está lento e existe shutdown concorrente.

**Ação:** Fechar host antes de verify acabar.

**Obrigatório observar:** Verificação não prende loop/força; resultado tardio não reabre guard.

## C4T-32 · T02 · C4-04

**Camada:** journal real/fault points. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Erro antes de fila, depois de fila, antes do commit, depois do commit.

**Ação:** Renew/revoke em cada ponto.

**Obrigatório observar:** Classificação por prova, não tipo genérico de exceção; nenhum busy eterno seguro.

## C4T-33 · T02 · C4-04

**Camada:** journal real/fault points. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Await cancelado após admissão do CAS.

**Ação:** Deixar unidade commit e consultar estado.

**Obrigatório observar:** Contexto aplica só quando permitido; tarefa rastreada; não supor rollback.

## C4T-34 · T02 · C4-04

**Camada:** concorrência. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Callback de tentativa antiga retido; outra tentativa possui token novo.

**Ação:** Liberar callback antigo.

**Obrigatório observar:** Não limpa nem aplica contexto da reserva nova.

## C4T-35 · T02 · C4-04

**Camada:** concorrência. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Renew pendente, seguido por fence de revogação/draining.

**Ação:** Commit tardio do renew.

**Obrigatório observar:** Não reabre concessão de trabalho nem restaura permissions removidas.

## C4T-36 · T02 · C4-04

**Camada:** fault injection. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** CAS falha e leitura de reconciliação também falha.

**Ação:** Expirar lease e pedir força.

**Obrigatório observar:** Unknown explícito e contenção independente; erro não vira sucesso.

## C4T-37 · T06 · C4-05

**Camada:** Node/layout. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Optional ausente, depois instalada; peer opcional ausente.

**Ação:** Calcular e executar layouts suportados.

**Obrigatório observar:** Ausência normal documentada; presença relevante altera identidade.

## C4T-38 · T06 · C4-05

**Camada:** Node/layout. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Duas dependências resolvem versões distintas do mesmo nome.

**Ação:** Modificar só uma versão.

**Obrigatório observar:** Topologia preservada; digest não colide por prefixo deps/name.

## C4T-39 · T06 · C4-05

**Camada:** Node/layout. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Instalação idêntica copiada para outra pasta; irmão irrelevante adicionado.

**Ação:** Comparar build e binding.

**Obrigatório observar:** Build igual; binding físico diferente; irmão irrelevante fora do conjunto.

## C4T-40 · T06 · C4-05

**Camada:** layout/security. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Symlink/reparse sai da raiz; nome inválido com traversal.

**Ação:** Tentar qualificar.

**Obrigatório observar:** Rejeição antes de ler conteúdo externo ou execução.

## C4T-41 · T06 · C4-05

**Camada:** migração. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Candidato antigo com algoritmo v2 parcial salvo.

**Ação:** Carregar após nova versão.

**Obrigatório observar:** Não qualifica por fallback silencioso; histórico preservado e reprepare exigido.

## C4T-42 · T06 · C4-05

**Camada:** provider real. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Pi do build efetivamente suportado, com paths e env aprovados.

**Ação:** Calcular hash, iniciar e executar fluxo qualificado.

**Obrigatório observar:** Digest/versão/capacidades e limites registrados; sem alegar todos layouts.

## C4T-43 · T07 · C4-06

**Camada:** unitário. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Tamanho exato, +1, múltiplos arquivos cuja soma excede no último.

**Ação:** Calcular com caps reduzidos e spy de leitura.

**Obrigatório observar:** Exato permitido; excedente recusado antes do read além do orçamento.

## C4T-44 · T07 · C4-06

**Camada:** fault injection filesystem. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Arquivo cresce entre stat e leitura.

**Ação:** Continuar streaming.

**Obrigatório observar:** Contador real interrompe; não ultrapassa cap silenciosamente.

## C4T-45 · T07 · C4-06

**Camada:** unitário filesystem. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Muitos diretórios vazios/profundidade com limites pequenos.

**Ação:** Enumerar pacote.

**Obrigatório observar:** Travessia limitada sem materializar todo rglob/sort primeiro.

## C4T-46 · T07 · C4-06

**Camada:** backend filesystem. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** FIFO/device/loop link em árvore selecionada.

**Ação:** Preparar build.

**Obrigatório observar:** Recusa antes de read bloqueante; limitação por SO documentada.

## C4T-47 · T07 · C4-06

**Camada:** concorrência. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Scans lentos, await cancelado repetidamente.

**Ação:** Repetir discovery/prepare e observar recursos.

**Obrigatório observar:** Filas/workers limitados; controle/loop responsivos.

## C4T-48 · TODOS · C4-07

**Camada:** regressão. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** C2/C3 mantidos e fixtures válidas.

**Ação:** Executar antes e depois.

**Obrigatório observar:** Nenhuma invariância relaxada; skips por camada identificados.

## C4T-49 · TODOS · C4-07

**Camada:** wheel isolado. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Wheel instalado fora da fonte com dependências declaradas.

**Ação:** Executar API/embedded/remote com -I.

**Obrigatório observar:** Sem import privado pelo consumidor e mesmo hash de wheel.

## C4T-50 · TODOS · C4-07

**Camada:** combinado. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Storage retido + open em callback + observer saturado.

**Ação:** Shutdown e retorno tardio das etapas.

**Obrigatório observar:** Sem spawn novo após draining; força disponível para ownership já existente.

## C4T-51 · TODOS · C4-07

**Camada:** migração. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Journal real da versão de entrada com receipts/unknown.

**Ação:** Upgrade interrompido e retomado em pontos controlados.

**Obrigatório observar:** Dados preservados; falha de migração não concede replay.

## C4T-52 · TODOS · C4-07

**Camada:** dois hosts reais E2. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Server local e remoto Connector usando mesmo wheel.

**Ação:** Abrir/interrupt/stop, perder conexão e recuperar.

**Obrigatório observar:** MCP HTTP direto, consumo exclusivo e resultado incerto preservados.

## C4T-53 · TODOS · C4-07

**Camada:** qualificação de release. **Estado na auditoria:** `NOT_RUN`.

**Preparação:** Resultados das demais camadas coletados.

**Ação:** Preencher decisão E0/E1/E2/E3 e manifesto.

**Obrigatório observar:** E1 exige backend real do escopo; E2/E3 não inferidos de smoke.
