# Matriz de regressões e aceite — correção do Core

**Total:** 129 cenários especificados. **Estado inicial:** todos `NOT_RUN`.

Esta matriz complementa os casos TK/J de R3 e as nove sementes históricas. Não representa 129 funções de teste já implementadas. Cada cenário pode exigir várias parametrizações; uma função que cobre vários cenários deve registrar a correspondência.

**Camadas:** determinístico/contrato (sem provider); processo contido; plataforma; provider real; integração de hosts; migração; artefato. `PASS` requer evidência da camada declarada, não apenas um double. `BLOCKED` deve informar ambiente/dependência/owner; não substitui PASS.

**Foco de regressão:** validar o comportamento observável e a durabilidade. Não acoplar testes novos ao nome de lock ou à organização interna se a invariante pode ser comprovada pela API pública. Fakes podem instrumentar o efeito para contar writes/spawns, atrasos e cancelamentos.

**Relógios:** usar relógio injetado e barreiras para races. Testes temporais reais devem registrar runner/budgets e nunca aumentar timeout até mascarar bloqueio.


## PC00 — Reconciliar o HEAD, preservar evidências e criar a campanha de regressão

**Achados:** F01, F02, F03, F04, F05, F06, F07, G01, G02, G03, G04, G05, G06. **Gate:** Inventário de divergências do HEAD, ambiente reproduzível, cobertura inicial dos achados e classificação honesta dos resultados disponíveis.


### RC-00-01 — Linha de base íntegra

**Camada:** documental · **Status:** NOT_RUN.

**Preparação:** Clone com HEAD atual e ZIP de referência.

**Ação:** Gerar inventário e hashes; comparar o plano R3.

**Resultado obrigatório:** Nenhuma alteração pré-existente é perdida; divergências ficam registradas.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-00-02 — Sementes reproduzíveis

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Dependências locais instaladas; nenhuma credencial de provider.

**Ação:** Rodar ou portar os nove casos da auditoria.

**Resultado obrigatório:** Resultados atuais são capturados e vinculados aos originais; não se exige que o HEAD reproduza defeitos já corrigidos.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-00-03 — Ambiente restrito explicitado

**Camada:** plataforma · **Status:** NOT_RUN.

**Preparação:** Host sem recurso de guardian requerido.

**Ação:** Executar preflight diagnóstico e selecionar campanha lógica.

**Resultado obrigatório:** Restrição identificada; testes de contenção não recebem PASS fictício.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-00-04 — Sem efeitos na importação

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Wheel ou árvore limpa, ambiente sem configuração de usuários.

**Ação:** Importar pacote em subprocesso instrumentado.

**Resultado obrigatório:** Não abre sockets, inicia workers/processos, resolve segredos nem cria event loop global por importar.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-00-05 — Ausência dos outros repositórios

**Camada:** documental · **Status:** NOT_RUN.

**Preparação:** Somente clone Core disponível.

**Ação:** Preparar handoffs e executar consumidores mínimos.

**Resultado obrigatório:** Relatório não confunde mocks com Server/Connector reais; dependência externa fica rastreada.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC01 — Remover I/O SQLite bloqueante do loop e preservar durabilidade

**Achados:** F04. **Gate:** Conformance anterior preservado; contenção SQLite não bloqueia timers do host; cancelamento e shutdown do worker têm resultados rastreáveis.


### RC-01-01 — SQLite retido por outro escritor

**Camada:** integração local · **Status:** NOT_RUN.

**Preparação:** Outra conexão segura BEGIN IMMEDIATE; ticker usa loop do Core.

**Ação:** Enfileirar gravação e manter lock por mais de 350 ms em host de teste calibrado.

**Resultado obrigatório:** Ticker progride durante a retenção; thread IDs provam SQL fora do loop; erro/commit é fiel.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-02 — Cancelamento antes da fila

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Fila bloqueada por barreira, request ainda não aceito.

**Ação:** Cancelar chamador antes do enqueue.

**Resultado obrigatório:** Nenhuma transação e nenhum recibo de efeito; erro/cancelamento documentado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-03 — Cancelamento durante commit

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Barreira entre início da transação e retorno do COMMIT.

**Ação:** Cancelar await e liberar o worker.

**Resultado obrigatório:** Resultado durável é recuperável; não duplicar transação por cancelamento.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-04 — Conflito de operações

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Mesmo namespace e ID com payloads diferentes.

**Ação:** Submeter de duas tarefas/instâncias controladas.

**Resultado obrigatório:** Uma admissão válida ou conflito tipado; o hash semântico não muda com scheduling.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-05 — Fila normal saturada

**Camada:** stress · **Status:** NOT_RUN.

**Preparação:** Limites pequenos, worker ocupado e buffer normal cheio.

**Ação:** Enviar controles e novas operações normais.

**Resultado obrigatório:** Backpressure antes do efeito; reserva de controles respeitada; memória limitada.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-06 — Checkpoint lento

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Checkpoint bloqueado/injetado no worker.

**Ação:** Rodar controles de sessão no loop.

**Resultado obrigatório:** Loop e rota física de contenção permanecem ativos; checkpoint não finge conclusão.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-07 — Disco cheio no resultado

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Intenção já durável; falha ao persistir resultado.

**Ação:** Completar efeito nativo e tentar registrar receipt.

**Resultado obrigatório:** Não declarar retry_safe; journal anterior permite reconstruir OUTCOME_UNKNOWN.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-08 — Consumer de eventos lento

**Camada:** integração local · **Status:** NOT_RUN.

**Preparação:** Grande volume de eventos com ACK lento.

**Ação:** Ler em páginas e suspender consumidor entre yields.

**Resultado obrigatório:** Nenhuma transação retida por yield; quotas e gaps declarados continuam válidos.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-09 — Reopen e conformance

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Journal/ledger em stores privados.

**Ação:** Rodar kits de conformance e restart existentes.

**Resultado obrigatório:** Claims, CAS, receipts, eventos e ACK mantêm semântica após reopen.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-01-10 — Falha/stop do worker

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Worker encerrando ou falhando durante request.

**Ação:** Enviar nova operação e pedir aclose simultaneamente.

**Resultado obrigatório:** Novas admissões recusadas, in-flight rastreado; sem threads órfãs declaradas encerradas.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC02 — Unificar contenção independente, leases e desligamento

**Achados:** F01, G05. **Gate:** Expiração e revogação acionam contenção com send/storage travados; sem kill externo, sucesso fictício ou liberação prematura de slots.


### RC-02-01 — Lease com send travado

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Fake send bloqueado por Event; grace zero e relógio controlado.

**Ação:** Expirar lease sem liberar send.

**Resultado obrigatório:** Aciona close/força independente no budget configurado; nenhum novo submit.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-02 — Força real não herda lock

**Camada:** processo contido · **Status:** NOT_RUN.

**Preparação:** Peer gerenciado trava protocolo e ignora fechamento gentil.

**Ação:** Expirar lease em host com backend qualificado.

**Resultado obrigatório:** Backend força a árvore própria sem esperar mutex do write; observação comprova ou relata unknown.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-03 — Storage travado na expiração

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Journal worker bloqueado durante evento de lease.

**Ação:** Expirar e ultrapassar grace.

**Resultado obrigatório:** Força é acionada sem aguardar persistência; sem ACK durável inventado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-04 — Renovação antes de fechar

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Watcher acorda próximo ao deadline; renovação válida faz CAS.

**Ação:** Intercalar renovação antes da escalada irreversível.

**Resultado obrigatório:** Watcher revalida contexto; não encerra uma sessão com lease válida por snapshot velho.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-05 — Renovação tardia

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Contenção já iniciada para geração antiga.

**Ação:** Receber renew com contexto aparentemente mais novo.

**Resultado obrigatório:** Não ressuscita nem reaproveita instância; resultado tipado preserva estado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-06 — Revoke versus envio

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Send em fila ou ativo; revogação autorizada.

**Ação:** Aplicar fence/CAS, atrasar commit e soltar worker nativo.

**Resultado obrigatório:** Nenhum novo efeito stale; resposta distingue pendência local de revogação durável.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-07 — Stop concorrente

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Três tarefas pedem lease_close, stop explícito e shutdown.

**Ação:** Disparar simultaneamente.

**Resultado obrigatório:** Uma coordenação física idempotente, sem dupla liberação de slot.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-08 — Backend não comprova morte

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** force_stop retorna, observe continua unknown.

**Ação:** Aguardar budget e consultar sessão.

**Resultado obrigatório:** Não marca stopped nem libera slot; shutdown reporta unknown.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-09 — Thread nativa retorna tarde

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Task cancelada, thread ainda ativa.

**Ação:** Forçar parada e depois liberar thread.

**Resultado obrigatório:** Completion tardia não muda sessão encerrada para RUNNING nem dispara write novo.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-10 — Attach sob expiração

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Sessão externa attach marcada como não própria.

**Ação:** Expirar ou desligar host.

**Resultado obrigatório:** Só detach/fechamento de controle; nenhum signal/kill do alvo externo.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-02-11 — Relógio e budgets

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Clock rollback, saltos e múltiplas tentativas de close.

**Ação:** Exercitar deadlines.

**Resultado obrigatório:** Não prolonga lease nem reinicia budget a cada tentativa; estados continuam conservadores.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC03 — Revalidar autorização na fronteira real do efeito

**Achados:** F02. **Gate:** Atrasos em qualquer await/fila não permitem efeito sob contexto stale; crash/cancelamento preservam idempotência e incerteza reais.


### RC-03-01 — Expiração durante admit

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Journal fake bloqueia admit e clock é controlável.

**Ação:** Avançar clock antes de retornar admit.

**Resultado obrigatório:** Zero efeito; recusa tipada e receipt consistente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-02 — Expiração durante marker

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Marca de possível efeito persiste e relógio avança.

**Ação:** Retornar ao kernel depois de expirar.

**Resultado obrigatório:** Zero efeito e not-sent somente se comprovado; regressão original coberta.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-03 — Thread inicia tarde

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Executor de thread ocupado antes do write.

**Ação:** Enfileirar trabalho válido e expirar antes da thread iniciar.

**Resultado obrigatório:** Guarda nativa impede o efeito, mesmo que checagem no loop tenha passado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-04 — Revoke entre marker e write

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Barreira no ponto pré-efeito; fence mutável.

**Ação:** Revogar e depois liberar barreira.

**Resultado obrigatório:** Nenhum novo write com geração anterior.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-05 — Revogação após início de efeito

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Primeiro byte ou spawn já observado.

**Ação:** Revogar e interromper comunicação antes do resultado.

**Resultado obrigatório:** Possível efeito permanece; PC02 contém; sem not-sent nem replay.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-06 — Controle seguro com lease expirada

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Sessão própria com scope correto e deadline vencido.

**Ação:** Solicitar interrupt/close e comparar com submit/approval permissiva.

**Resultado obrigatório:** Controle de contenção permitido conforme contrato; novo trabalho não.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-07 — Controle fora do escopo

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Agente/binding/owner incorreto com ação close.

**Ação:** Pedir contenção externa de sessão alheia.

**Resultado obrigatório:** Rejeição; exceção temporal de close não contorna identidade/ownership.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-08 — Recusa com disco cheio

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Marca durável existe, nenhum efeito enviado, record_not_sent falha.

**Ação:** Recusar no pré-write e reabrir o journal.

**Resultado obrigatório:** Estado conservador consultável, sem promover volátil a durável nem repetir efeito.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-09 — Crash após efeito

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Peer grava contador persistente antes da resposta.

**Ação:** Matar host entre efeito e receipt.

**Resultado obrigatório:** Reconciliação unknown; retry mesmo ID não aumenta contador.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-03-10 — Geração e clocks alterados

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Revisão/owner/connection atualizados e clock rollback.

**Ação:** Tentar efeito com snapshot anterior.

**Resultado obrigatório:** Fences prevalecem; deadline não se estende implicitamente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC04 — Tratar fim de stream, cancelamento do observador e falta de observabilidade

**Achados:** F03. **Gate:** EOF inesperado bloqueia trabalho e fica observável; EOF esperado não gera erro falso; process/turn/handoff continuam semanticamente distintos.


### RC-04-01 — EOF com processo vivo

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Fake iterator encerra normalmente, observe diz alive.

**Ação:** Enviar novo submit.

**Resultado obrigatório:** EVENT_STREAM_UNAVAILABLE ou erro tipado equivalente antes de write.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-04-02 — EOF com journal travado

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Evento de erro não consegue persistir de imediato.

**Ação:** Tentar novo trabalho durante bloqueio.

**Resultado obrigatório:** Fence já ativo; contenção não espera journal.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-04-03 — Fechamento esperado

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Core pede close e depois esgota o iterador.

**Ação:** Aguardar completion.

**Resultado obrigatório:** Sem erro falso de perda de canal; resultado de stop observável.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-04-04 — Cancelamento inesperado

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Pump cancelado fora de shutdown.

**Ação:** Tentar submit e consultar sessão.

**Resultado obrigatório:** Não fica gravável nem parece saudável; incidente registrado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-04-05 — Terminal de turno sem EOF

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Peer emite terminal e mantém stream aberto.

**Ação:** Executar segundo turno.

**Resultado obrigatório:** Sessão reutilizada normalmente; não confundir terminal com fim da conexão.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-04-06 — Evento terminal seguido de EOF

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Terminal já persistido; EOF ocorre imediatamente depois.

**Ação:** Reconciliar turno e sessão.

**Resultado obrigatório:** Turno mantém resultado observado; sessão pode estar degradada separadamente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-04-07 — Approval pendente no EOF

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Request persistido antes da perda.

**Ação:** Enviar approve depois do fence.

**Resultado obrigatório:** Não permite novo efeito com correlação perdida; operação recusada fielmente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-04-08 — Incidente único

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** EOF concorre com exception/stop/notificação repetida.

**Ação:** Ler e repetir eventos por cursor.

**Resultado obrigatório:** Um incidente lógico por epoch, sem nova execução nem duplicação de completion.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC05 — Uniformizar IDs, erros e leitura de histórico legado

**Achados:** F05. **Gate:** IDs novos válidos são admitidos e reconciliáveis; inválidos são recusados antes de efeito; histórico dev0 continua consultável sem reexecução.


### RC-05-01 — Fronteiras de comprimento

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** IDs com 0,1,159,160,161,256,257 caracteres.

**Ação:** Open/submit e reconcile para todos.

**Resultado obrigatório:** 1–160 válidos se demais campos válidos; outros recusados tipadamente antes de efeito.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-02 — Tipos não textuais

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** None, bool, int, bytes, containers e objetos customizados.

**Ação:** Submeter como ID.

**Resultado obrigatório:** Sem cast; CoreError de validação, sem journal mutável.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-03 — Unicode e limite de bytes

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Acentos, astral, combinações, surrogate inválido e frames grandes.

**Ação:** Validar em Python e schema serializado.

**Resultado obrigatório:** Mesma aceitação por campo; teto de bytes separado; nenhuma normalização silenciosa.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-04 — Todo admitido reconcilia

**Camada:** propriedade · **Status:** NOT_RUN.

**Preparação:** Gerador de IDs válidos e namespaces.

**Ação:** Admitir e reconciliar antes/depois de restart.

**Resultado obrigatório:** Mesmo ID retorna evidência correta sem ValueError.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-05 — Batch inválido no fim

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Batch com 256 IDs válidos e item inválido adicional/dentro.

**Ação:** Consultar/submeter conforme operação suportada.

**Resultado obrigatório:** Validação consistente e nenhuma gravação parcial por lote malformado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-06 — Legado longo

**Camada:** migração · **Status:** NOT_RUN.

**Preparação:** Journal de dev0 contendo ID de 161/256 persistido.

**Ação:** Abrir versão corrigida e consultar pela porta legada.

**Resultado obrigatório:** Registro exato acessível; novos IDs longos continuam proibidos.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-07 — Legado não reexecuta

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** ID longo antigo com possível efeito.

**Ação:** Tentar reenviar via API normal e via leitura legada.

**Resultado obrigatório:** Nenhum efeito adicional; diagnóstico não gera autorização de replay.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-08 — Namespaces e prefixos

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Mesmo ID em dois servidores; prefixo interno reservado.

**Ação:** Consultar com escopo trocado e admitir ID interno externo.

**Resultado obrigatório:** Sem vazamento/cruzamento; prefixo interno rejeitado onde reservado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-05-09 — Hash e rekey

**Camada:** migração · **Status:** NOT_RUN.

**Preparação:** Cópia de banco com recibos e hashes pré-fix.

**Ação:** Rodar upgrade, consulta e export redigido.

**Resultado obrigatório:** IDs/hashes imutáveis; não truncar nem migrar efeitos para novas identidades.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC06 — Publicar composição real e contrato suportado dos consumidores

**Achados:** G01. **Gate:** Dois consumidores mínimos independentes usam somente API pública; composição real e journal alternativo funcionam; não há dependência de classes privadas nos hosts.


### RC-06-01 — EmbeddedHost público

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Wheel instalado em venv fora do repo.

**Ação:** Instanciar, abrir peer, submeter, ler eventos, interromper, parar e encerrar.

**Resultado obrigatório:** Só imports públicos; nenhum Connector app requerido.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-02 — RemoteHost público

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Segundo processo consumidor sem importar Server/Connector.

**Ação:** Usar mesma factory e artefato com contexto de outro executor.

**Resultado obrigatório:** Mesma semântica e nenhum transporte remoto dentro do Core.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-03 — Imports privados barrados

**Camada:** estático/contrato · **Status:** NOT_RUN.

**Preparação:** Lista de exemplos e smokes de consumidores.

**Ação:** Verificar imports AST e executar exemplos.

**Resultado obrigatório:** Não importa módulos privados native nem usa conexão interna do journal.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-04 — Protocol completo

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Implementação e RuntimeCore público.

**Ação:** Comparar chamadas e type-check, incluindo persisted_lease.

**Resultado obrigatório:** Nenhum método documentado fica fora do Protocol; signatures compatíveis.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-05 — Journal alternativo

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Implementação host-owned de Journal sem herança concreta.

**Ação:** Rodar conformance/restart/runtime mínimo.

**Resultado obrigatório:** Mesmas garantias, sem acoplamento SQLite oculto.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-06 — Recursos injetados

**Camada:** integração local · **Status:** NOT_RUN.

**Preparação:** Dois runtimes com resources host-owned.

**Ação:** Encerrar um deles e consultar o outro.

**Resultado obrigatório:** Não fecha recursos alheios; threads/processos próprios são encerrados corretamente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-07 — Erro em construção/start

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Callback de environment ou preparação falha.

**Ação:** Criar/compor e iniciar sessão.

**Resultado obrigatório:** Sem leak, sem secret logs, sem inventar efeito iniciado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-08 — Bundle público e offline

**Camada:** artefato · **Status:** NOT_RUN.

**Preparação:** Wheel sem árvore-fonte, rede desligada.

**Ação:** Ler schemas/manifest e verificar digest.

**Resultado obrigatório:** Recursos encontrados offline e revision igual nos dois consumers.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-06-09 — Sem side effect de builder

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Ambiente com credenciais sentinela e detector de spawn/network.

**Ação:** Construir opções/factory sem chamar open.

**Resultado obrigatório:** Sem resolução de segredo, rede, provider, loop global ou subprocesso implícito.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC07 — Liberar objetos de sessões encerradas sem perder histórico ou ownership

**Achados:** F06. **Gate:** Muitos ciclos terminados não retêm adapters pesados; consultas históricas permanecem corretas; sessões incertas não são apagadas.


### RC-07-01 — Doze ciclos da auditoria

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** max_owned_sessions baixo e factory com referências fracas.

**Ação:** Abrir/fechar doze sessões e liberar referências do teste.

**Resultado obrigatório:** Adapters antigos tornam-se coletáveis; cache leve respeita limite próprio.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-07-02 — Mil ciclos em lotes

**Camada:** stress · **Status:** NOT_RUN.

**Preparação:** Limites explícitos, coleta e instrumentação por lote.

**Ação:** Executar 1.000 ciclos sintéticos, capturando tendência.

**Resultado obrigatório:** Contagem de objetos/tasks encerrados não cresce linearmente; memória pesada limitada.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-07-03 — Reconciliação depois de evict

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Sessão fechada e removida do registry vivo.

**Ação:** Consultar receipt/eventos e repetir operação antiga.

**Resultado obrigatório:** Histórico disponível; nenhum replay de efeito.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-07-04 — Sink permanentemente lento

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Callback de notificação bloqueado.

**Ação:** Encerrar sessão e continuar outras.

**Resultado obrigatório:** Sem adapter pesado retido ilimitadamente; backlog durável bounded, sem ACK fictício.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-07-05 — Resultado unknown

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Backend não confirma stop e existe possível efeito.

**Ação:** Aplicar pressão no cache.

**Resultado obrigatório:** Ownership/slot preservados; não expulsar unknown para liberar capacidade.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-07-06 — Callback tardio

**Camada:** determinístico · **Status:** NOT_RUN.

**Preparação:** Task nativa retoma após teardown.

**Ação:** Entregar completion/evento de epoch antigo.

**Resultado obrigatório:** Não reintroduz sessão viva nem associa resposta a sessão nova.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-07-07 — Query após restart

**Camada:** integração local · **Status:** NOT_RUN.

**Preparação:** Journal persistido e cache vazio.

**Ação:** Reabrir Core e consultar sessão histórica.

**Resultado obrigatório:** Relato distingue histórico de liveness e não reivindica processo automaticamente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC08 — Aplicar o modelo solicitado e tornar configuração efetiva verificável

**Achados:** F07. **Gate:** Codex e Claude recebem a seleção nos pontos nativos corretos; Pi não regride; o estado relatado distingue intenção de confirmação.


### RC-08-01 — Modelo explícito Codex

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Factory real com peer/spy de protocolo e intenção marker.

**Ação:** Preparar e abrir sessão.

**Resultado obrigatório:** Marker chega ao mecanismo nativo correto, não apenas ao hash.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-08-02 — Modelo explícito Claude

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Factory real com spy e modo stream qualificado.

**Ação:** Preparar e abrir.

**Resultado obrigatório:** Modelo está no argv/config autorizado corretamente delimitado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-08-03 — Pi preservado

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Modelo explícito e layout Node+CLI aprovado.

**Ação:** Preparar e abrir peer.

**Resultado obrigatório:** Modelo continua aplicado e argv obrigatório não é perdido.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-08-04 — Default ausente

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** LaunchIntent.model=None e configuração aprovada.

**Ação:** Comparar operação anterior e corrigida.

**Resultado obrigatório:** Default documentado permanece; não inventar override ou effective_model.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-08-05 — Modelo não suportado

**Camada:** contrato/provider · **Status:** NOT_RUN.

**Preparação:** Nome inválido ou capability ausente.

**Ação:** Solicitar e observar estágio de rejeição.

**Resultado obrigatório:** Falha clara, sem fallback; possible_effect reflete o que realmente começou.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-08-06 — Resume conflitante

**Camada:** segurança/contrato · **Status:** NOT_RUN.

**Preparação:** Thread anterior com outro profile/model e resume grant.

**Ação:** Pedir retomada com escolha divergente.

**Resultado obrigatório:** Não troca modelo ou ignora intenção silenciosamente; política e fingerprint prevalecem.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-08-07 — Observado versus solicitado

**Camada:** provider real · **Status:** NOT_RUN.

**Preparação:** Provider informa ou omite o modelo efetivo.

**Ação:** Ler snapshot/eventos de início/uso.

**Resultado obrigatório:** Confirmação só quando observada; campo não reportado continua desconhecido.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-08-08 — Entrada especial e redaction

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Modelo com espaços/Unicode/metacaracteres, secrets sentinela no env.

**Ação:** Gerar configuração e logs.

**Resultado obrigatório:** Sem shell injection ou vazamento; validação conforme contrato do modelo.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC09 — Separar qualificação portável de binding físico local

**Achados:** G02. **Gate:** Mesmo build aprovado em caminhos diferentes conserva qualificação; mover/trocar instalação continua invalidando o binding anterior.


### RC-09-01 — Build igual em paths diferentes

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Copiar mesmo conjunto de artefatos para dois diretórios.

**Ação:** Calcular identidades e consultar qualificação.

**Resultado obrigatório:** build_identity igual; binding_fingerprint diferente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-09-02 — Pi dependência alterada

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** cli.js igual, módulo/dependência executável muda.

**Ação:** Recalcular e tentar open.

**Resultado obrigatório:** Mudança material identificada; não usa qualificação anterior cegamente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-09-03 — Version string falsificada

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Dois binários dizem mesma versão mas têm bytes diferentes.

**Ação:** Calcular build e capabilities.

**Resultado obrigatório:** Não são promovidos ao mesmo build só pelo texto da versão.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-09-04 — Drift após prepare

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Binding aprovado e prepared válido.

**Ação:** Trocar path/symlink/conteúdo antes de open.

**Resultado obrigatório:** PROFILE_DRIFT ou equivalente antes de spawn.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-09-05 — Três estados separados

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Candidato encontrado mas não aprovado; outro aprovado mas não qualificado.

**Ação:** Consultar inventory/prepare.

**Resultado obrigatório:** Estados claros; discovery sozinho não concede execução.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-09-06 — Capacidade por interseção

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Build suporta operação mas host ou perfil a nega.

**Ação:** Tentar operação.

**Resultado obrigatório:** Capacidade não pode ser inventada por manifesto ou configuração.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-09-07 — Qualificação antiga

**Camada:** migração · **Status:** NOT_RUN.

**Preparação:** Catálogo dev0 com fingerprint path-dependent.

**Ação:** Migrar e consultar registro.

**Resultado obrigatório:** Sem promoção automática inválida; histórico e limitação ficam preservados.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-09-08 — Cache stale e plugins

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Cache preenchido; artefatos/plugins aprovados mudam.

**Ação:** Reusar prepared/cache.

**Resultado obrigatório:** Invalidação correta; qualificação não cobre código novo implicitamente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC10 — Concluir discovery dos layouts suportados sem executar wrappers arbitrários

**Achados:** G03. **Gate:** Instalações comuns testadas são detectadas e preparadas sem localizar manualmente cli.js; layouts não suportados falham com orientação segura.


### RC-10-01 — Pi layout usual

**Camada:** contrato/plataforma · **Status:** NOT_RUN.

**Preparação:** Fixture de instalação Node+Pi do layout declarado.

**Ação:** Descobrir sem paths internos fornecidos.

**Resultado obrigatório:** Candidato composto válido, origem e qualificação explícitas.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-10-02 — Windows path com espaços/Unicode

**Camada:** plataforma · **Status:** NOT_RUN.

**Preparação:** Shim conhecido apontando a instalação aprovada.

**Ação:** Resolver e preparar argv.

**Resultado obrigatório:** Tokens preservados, sem shell concat/injeção.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-10-03 — Wrapper hostil

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Arquivo chama comandos extras, URLs ou expansão dinâmica.

**Ação:** Descobrir passivamente.

**Resultado obrigatório:** Não executar wrapper; diagnóstico e zero side effect.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-10-04 — PATH/cwd malicioso

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Homônimo no cwd/raiz gravável antes do binário aprovado.

**Ação:** Descobrir e reutilizar binding.

**Resultado obrigatório:** Não troca escolha aprovada nem executa candidato não confiável.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-10-05 — Múltiplas instalações

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Duas versões/binários válidos detectados.

**Ação:** Listar e depois mudar ordem do PATH.

**Resultado obrigatório:** Ambiguidade explícita; seleção aprovada estável até drift.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-10-06 — Probe travado/flood

**Camada:** processo contido · **Status:** NOT_RUN.

**Preparação:** Peer de versão não termina ou escreve infinitamente.

**Ação:** Executar probe com limites pequenos.

**Resultado obrigatório:** Contenção/limites operam; candidato não vira qualificado pelo timeout.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-10-07 — Symlink trocado

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Resolver encontra alvo, depois link muda.

**Ação:** Preparar/open.

**Resultado obrigatório:** Drift bloqueia efeito e identifica etapa.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-10-08 — Sem autenticação de agente por discovery

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Grande catálogo de identidades no host ou server mock.

**Ação:** Chamar discovery de binários.

**Resultado obrigatório:** Não busca/lista/importa chaves de agentes nem autentica usuário Nexus.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC11 — Preflight e qualificação real dos backends de contenção

**Achados:** G05. **Gate:** Ambiente incompatível falha cedo e de forma prescritiva; onde suporte é anunciado, árvore própria e falha do owner são qualificadas.


### RC-11-01 — Proc children indisponível

**Camada:** plataforma · **Status:** NOT_RUN.

**Preparação:** Fixture/host restrito reproduz falta de interface requerida.

**Ação:** Preflight e tentativa de open.

**Resultado obrigatório:** Falha antes de provider com causa tipada; nenhum sucesso Linux genérico.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-02 — Permissão de backend negada

**Camada:** plataforma · **Status:** NOT_RUN.

**Preparação:** Job/pidfd/subreaper requerido negado conforme backend.

**Ação:** Checar e iniciar.

**Resultado obrigatório:** Não usa fallback inseguro; evita efeito produtivo.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-03 — Árvore filho/neto

**Camada:** processo contido · **Status:** NOT_RUN.

**Preparação:** Peer cria descendants dentro de container próprio.

**Ação:** Stop, força e observe.

**Resultado obrigatório:** Todos os recursos abrangidos terminam ou ficam explicitamente unknown; nenhum alheio afetado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-04 — Owner morre

**Camada:** plataforma/fault · **Status:** NOT_RUN.

**Preparação:** Peer isolado e backend qualificado.

**Ação:** Matar supervisor de teste de forma abrupta.

**Resultado obrigatório:** Guard/job cumpre contrato demonstrado; evidência de contenção física, não só retorno de syscall.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-05 — PID reutilizado

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Birth evidence histórica e PID agora pertence a outro processo.

**Ação:** Inspecionar/reconciliar/conter.

**Resultado obrigatório:** Não mata PID alheio; histórico não concede ownership.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-06 — Slot reservado sem prova

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Prova de parada ausente após falha.

**Ação:** Tentar abrir nova sessão na capacidade limite.

**Resultado obrigatório:** Bloqueio e diagnóstico; sem purge para fazer teste verde.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-07 — Probe com backend indisponível

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Discovery deseja executar --version mas preflight falha.

**Ação:** Chamar probe ativo.

**Resultado obrigatório:** Não executa código não contido; inventário reporta limitação.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-08 — Preflight sem segredos

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Secret provider sentinela registra acessos.

**Ação:** Rodar preflight que falha.

**Resultado obrigatório:** Zero resolução de credenciais de provider/agente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-11-09 — Shutdown e logout suportados

**Camada:** plataforma · **Status:** NOT_RUN.

**Preparação:** Sessão/serviço de teste configurado conforme backend.

**Ação:** Fechar owner/sessão do SO sob cenário autorizado.

**Resultado obrigatório:** Resultado documentado por backend; não inferir que todos os modos SO se comportam igual.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC12 — Integrar attach pela API pública e preservar processos externos

**Achados:** G04. **Gate:** Attach/detach operam pelo contrato público em combinação qualificada; alvos externos nunca recebem kill implícito; limitações continuam explícitas.


### RC-12-01 — Múltiplos alvos

**Camada:** contrato/segurança · **Status:** NOT_RUN.

**Preparação:** Duas conversas/processos externos elegíveis.

**Ação:** Escolher um alvo e abrir attach.

**Resultado obrigatório:** Somente alvo aprovado recebe integração; nenhum autoattach ao primeiro.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-12-02 — Troca de alvo

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** PID/identidade muda entre seleção e attach.

**Ação:** Tentar conectar com evidence antiga.

**Resultado obrigatório:** Rejeita sem enviar comandos nem assumir posse.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-12-03 — Detach não mata

**Camada:** processo externo de teste · **Status:** NOT_RUN.

**Preparação:** Sessão attach qualificada em peer fora do ownership.

**Ação:** Stop/detach e verificar liveness externa.

**Resultado obrigatório:** Canal local fecha, processo externo permanece vivo.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-12-04 — Lease/revoke/shutdown externos

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Attach ativo com processo externo.

**Ação:** Expirar, revogar e desligar host em campanhas separadas.

**Resultado obrigatório:** Sem kill, apenas encerramento de controle dentro do escopo permitido.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-12-05 — Substrato incompatível

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Versão/SO não qualificado ou protocolo mudou.

**Ação:** Preparar/abrir attach.

**Resultado obrigatório:** Unsupported tipado; flag não é ligada para contornar falha.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-12-06 — Eventos e correlação reais

**Camada:** provider/substrato real · **Status:** NOT_RUN.

**Preparação:** Sessão externa de teste aprovada, versão registrada.

**Ação:** Executar operação permitida e observar resultado.

**Resultado obrigatório:** Eventos pertencem à conversa correta; nenhum terminal/handoff inventado.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-12-07 — Restart não reassume alvo

**Camada:** segurança · **Status:** NOT_RUN.

**Preparação:** Persistir referência de attach, reiniciar Core.

**Ação:** Consultar e tentar controlar sem nova validação.

**Resultado obrigatório:** Histórico não vira autorização de reattach ou PID signaling.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC13 — Qualificar modos gerenciados, MCP HTTP direto e integração dos dois hosts

**Achados:** G06. **Gate:** Um caminho local e um remoto em hosts distintos usam o mesmo adapter/wheel; providers/capacidades declarados têm evidência; itens não executados permanecem pendentes.


### RC-13-01 — Core+Server local

**Camada:** integração real · **Status:** NOT_RUN.

**Preparação:** Server com Core corrigido, sem app Connector instalado.

**Ação:** Abrir/controlar provider local pela API pública.

**Resultado obrigatório:** Mesmo adapter do Core; runtime termina de forma gerenciada.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-02 — Core+Connector remoto

**Camada:** integração real · **Status:** NOT_RUN.

**Preparação:** Máquina A Server sem binários/checkout/provider keys; máquina B Connector com Core.

**Ação:** Abrir e operar runtime em B.

**Resultado obrigatório:** A coordena sem resolver path remoto localmente; trabalho observado corretamente.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-03 — Mesmo wheel nas duas formas

**Camada:** artefato/integração · **Status:** NOT_RUN.

**Preparação:** Wheel SHA único entregue a ambos hosts.

**Ação:** Ler versões/manifest no runtime e comparar.

**Resultado obrigatório:** Artefatos idênticos; sem adaptações privadas ou cópia de adapter.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-04 — MCP direto real

**Camada:** integração real · **Status:** NOT_RUN.

**Preparação:** Harness com suporte MCP HTTP e configuração gerada.

**Ação:** Chamar ferramentas enquanto observa destinos.

**Resultado obrigatório:** Tráfego vai ao Server, não a porta/proxy do Connector.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-05 — Tools-only sem Connector

**Camada:** integração real · **Status:** NOT_RUN.

**Preparação:** Harness independente, não propriedade do daemon, MCP HTTP configurado.

**Ação:** Consumir ferramentas com Connector ausente/parado.

**Resultado obrigatório:** Acesso MCP funciona; teste não depende da sobrevida de runtime que stop deve encerrar.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-06 — Cliente somente stdio

**Camada:** contrato · **Status:** NOT_RUN.

**Preparação:** Harness não tem cliente MCP HTTP qualificado.

**Ação:** Solicitar configuração de Nexus MCP.

**Resultado obrigatório:** Diagnóstico sem fallback MCP stdio/proxy; integração nativa distinta só se suportada.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-07 — Pi extensão autorizada

**Camada:** provider/integração real · **Status:** NOT_RUN.

**Preparação:** Pi e recurso versionado do wheel; backend host restrito.

**Ação:** Context/claim/complete e ação fora do escopo.

**Resultado obrigatório:** Domínio no Server, rejeição fora do escopo; texto livre não vira comando.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-08 — Multi-turn e HITL

**Camada:** provider real · **Status:** NOT_RUN.

**Preparação:** Builds registrados de Codex/Claude/Pi conforme capacidades.

**Ação:** Dois turnos e decisões aprovadas/negadas/tardias.

**Resultado obrigatório:** Correlação correta; terminal, ACK, processo e handoff não são confundidos.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-09 — Desconexão e reconexão

**Camada:** integração/fault · **Status:** NOT_RUN.

**Preparação:** Operação com possível efeito no runtime remoto.

**Ação:** Cortar canal e reconectar antes/depois de grace.

**Resultado obrigatório:** Reconcilia sem replay automático; lease aplica limites locais.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-10 — Restart dos hosts

**Camada:** integração/fault · **Status:** NOT_RUN.

**Preparação:** Journal com recepções/efeitos e runtime de teste.

**Ação:** Reiniciar Server e Connector em cortes distintos.

**Resultado obrigatório:** Identidade preservada; PID histórico não vira ownership; unknown mantém bloqueio.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-11 — Pressão e fairness

**Camada:** stress · **Status:** NOT_RUN.

**Preparação:** Streams com flood e várias sessões/identidades.

**Ação:** Atrasar sink/journal e enviar controle urgente.

**Resultado obrigatório:** Buffers bounded e controles observáveis; um agente não esgota ilimitadamente recursos de outro.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-13-12 — Consumo exclusivo/handoff

**Camada:** integração real · **Status:** NOT_RUN.

**Preparação:** Mesmo agente tem MCP e runtime disponíveis.

**Ação:** Entregar tarefa e produzir turn terminal/complete.

**Resultado obrigatório:** Um consumidor lógico conforme Server; fim de turno não completa handoff sozinho.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


## PC14 — Fechar migrações, documentação, artefatos e gates de liberação

**Achados:** G01, G06. **Gate:** Artefato reproduzível/instalável e documentação coerente; nível de liberação explícito; migração e bloqueios rastreados; nenhuma publicação automática.


### RC-14-01 — Migração dev0 completa

**Camada:** migração · **Status:** NOT_RUN.

**Preparação:** Cópia do schema/dados dev0 com todos estados técnicos relevantes.

**Ação:** Migrar/reabrir e consultar.

**Resultado obrigatório:** Histórico, claims, slots e hashes preservados; consulta legada funciona.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-14-02 — Falha no meio da migração

**Camada:** fault injection · **Status:** NOT_RUN.

**Preparação:** Backup e barreira na migração.

**Ação:** Interromper transação/processo e reabrir.

**Resultado obrigatório:** Recuperação consistente, sem schema parcial usado como pronto.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-14-03 — Wheel fora da árvore

**Camada:** artefato · **Status:** NOT_RUN.

**Preparação:** Venv limpo e wheel construído.

**Ação:** Instalar e executar import/conformance/smoke.

**Resultado obrigatório:** Não depende de PYTHONPATH para src/tests nem de recursos fora do pacote.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-14-04 — Builds limpos comparados

**Camada:** artefato · **Status:** NOT_RUN.

**Preparação:** Dois diretórios limpos com toolchain registrada.

**Ação:** Construir e comparar conforme política reprodutível.

**Resultado obrigatório:** Digest igual quando prometido; diferenças normalizadas/causas não são ocultadas.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-14-05 — Sem MCP/daemon no Core

**Camada:** arquitetura · **Status:** NOT_RUN.

**Preparação:** Wheel e árvore-fonte final.

**Ação:** Auditar imports, entrypoints, sockets e exemplos.

**Resultado obrigatório:** Nenhum serviço/proxy/SDK MCP ou daemon operacional; stdio nativo permanece.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-14-06 — Release parcial honesto

**Camada:** documental · **Status:** NOT_RUN.

**Preparação:** Managed qualificado, attach/provider/SO ainda pendente.

**Ação:** Gerar relatório e validar gates.

**Resultado obrigatório:** E1/E2 podem ser entregues no escopo; E3 não recebe PASS.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-14-07 — Pin e integridade dos consumidores

**Camada:** artefato/integração · **Status:** NOT_RUN.

**Preparação:** Dois consumers com dependências explícitas.

**Ação:** Comparar wheel/manifest/API/NXL instalado.

**Resultado obrigatório:** Sem drift de schemas ou aliases para HEAD flutuante.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.


### RC-14-08 — Não publicação implícita

**Camada:** segurança/operacional · **Status:** NOT_RUN.

**Preparação:** Credenciais de publicação podem existir no ambiente.

**Ação:** Executar build/validação local e revisar comandos.

**Resultado obrigatório:** Nenhum upload/PyPI/release/push acionado como efeito colateral.

**Evidência:** registrar test node/parametrização, comando, exit code, SHA, ambiente, logs/traces redigidos e vínculo com o gate.
