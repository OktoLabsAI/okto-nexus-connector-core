# Matriz de aceite C5

56 cenários. Os estados abaixo são do snapshot auditado, não do produto após correção. `FAIL` significa cenário executado e requisito violado; `NOT_RUN` é especificação a implementar/executar. Um cenário pode mapear a múltiplos testes e um teste a múltiplos cenários, sem somar duplicatas.

## AC5-00-01 — Baseline e preservação

**Camada:** documental. **Estado na auditoria:** NOT_RUN.

**Preparação:** ZIP identificado e HEAD atual do executor.

**Ação:** Conferir hashes e diff; guardar dirty state antes de mudar.

**Resultado exigido:** Nenhum reset, remoção ou sobrescrita de trabalho posterior.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-00-02 — Regressões históricas

**Camada:** regressão. **Estado na auditoria:** NOT_RUN.

**Preparação:** C2, C3, 16 testes C4 e sementes C4 originais com adaptação documentada.

**Ação:** Executar em checkout e ambiente identificados.

**Resultado exigido:** Manter as asserções causais e separar provider ausente, plataforma e defeito.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-00-03 — Isolamento de dependências

**Camada:** empacotamento. **Estado na auditoria:** NOT_RUN.

**Preparação:** Ambiente com dependências exatas do pacote e de teste.

**Ação:** Importar no processo pai e em subprocesso -I; registrar versões.

**Resultado exigido:** Não diagnosticar ModuleNotFoundError de ambiente como falha funcional.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-00-04 — Inventário de efeitos

**Camada:** revisão. **Estado na auditoria:** NOT_RUN.

**Preparação:** Todos os adapters e bridges do escopo.

**Ação:** Mapear cada write/spawn, seus locks, filas e guardas.

**Resultado exigido:** Nenhum caminho produtivo sem decisão e prova própria.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-01-01 — Aprovação vence no write lock

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Pedido válido; transporte e serializador Codex reais; stdin controlado.

**Ação:** Bloquear lock, iniciar accept, esperar entrada, vencer relógio e liberar.

**Resultado exigido:** Zero bytes; recusa tipada anterior ao efeito; sem consumo indevido do pedido.

**Evidência existente:** test_u01_approval_guard_reaches_native_writer_after_lock[deadline]

## AC5-01-02 — Turno muda no write lock

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Mesmo caminho, turno 1 ativo.

**Ação:** Com accept esperando lock, trocar para turno 2 e liberar.

**Resultado exigido:** Nenhuma resposta permissiva de turno 1 atinge turno 2.

**Evidência existente:** test_u01_approval_guard_reaches_native_writer_after_lock[turn]

## AC5-01-03 — Spawn vence dentro do adaptador

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Runtime/kernel/journal reais; start Codex retido no lock; sentinela em spawn.

**Ação:** Vencer autorização depois da guarda da thread, liberar lock.

**Resultado exigido:** Primitiva spawn não chamada; nenhum slot liberado sem resultado conhecido.

**Evidência existente:** test_u02_spawn_guard_reaches_real_adapter_after_start_lock[deadline]

## AC5-01-04 — Shutdown enquanto start espera

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Mesma abertura com prazo ainda válido.

**Ação:** Fazer shutdown público enquanto start espera; liberar lock.

**Resultado exigido:** Nenhum spawn posterior ao fechamento da guarda.

**Evidência existente:** test_u02_spawn_guard_reaches_real_adapter_after_start_lock[shutdown]

## AC5-01-05 — Controle positivo: turno normal

**Camada:** unit/fault-injection. **Estado na auditoria:** PASS.

**Preparação:** Writer Codex conectado ao DispatchGuards do adapter.

**Ação:** Vencer prazo durante write lock em send_turn normal.

**Resultado exigido:** Continua recusando a escrita após C5.

**Evidência existente:** test_control_c4_guarded_turn_refuses_after_real_write_lock

## AC5-01-06 — Input sensível tardio

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Pedido de input de turno válido, dados de laboratório.

**Ação:** Reter writer e revogar/mudar geração antes de liberar.

**Resultado exigido:** Não transmitir input; erro sem conteúdo sensível.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-01-07 — Negar/interrupt após prazo

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Pedido e alvo ainda corretos; prazo vencido.

**Ação:** Enviar deny/cancel/interrupt nas rotas específicas.

**Resultado exigido:** Controle seguro permanece possível; nunca traduzir em accept ou novo turno.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-01-08 — Duas operações na mesma thread reutilizada

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Duas sessões/identidades com contextos diferentes.

**Ação:** Despachar em sequência e concorrência; uma lança erro.

**Resultado exigido:** Guard é por operação, removido em finally e não reutilizado pela outra sessão.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-01-09 — Write parcial e flush

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Stdin conta primeira escrita e falha no flush.

**Ação:** Produzir efeito parcial seguido de erro/expiração.

**Resultado exigido:** OUTCOME_UNKNOWN/possível efeito; nunca not_sent ou reenvio cego.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-01-10 — Pi e Claude pós-lock

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Transportes reais desses adapters com peers, sem provider real.

**Ação:** Aplicar barreiras em seus locks para turn, input e approvals suportados.

**Resultado exigido:** Mesmas regras por rota; features ausentes não anunciadas.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-01-11 — Handshake e janela pré-spawn

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Adapter cria handles/espera inicialização em pontos explícitos.

**Ação:** Bloquear antes da criação e depois da criação, então invalidar.

**Resultado exigido:** Antes: recusa sem spawn; depois: ownership e contenção, não not_sent global.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-01-12 — Backend de SO

**Camada:** processo real. **Estado na auditoria:** NOT_RUN.

**Preparação:** Executável inofensivo num SO qualificado e identidade de processo possuído.

**Ação:** Repetir uma corrida no backend real sem depender de provider.

**Resultado exigido:** Controle alcança handle correto; nenhum processo externo é afetado.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-02-01 — Resultado tardio de open cancelado

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Start em thread controlada; runtime real; início ainda pendente.

**Ação:** Cancelar chamador, chamar shutdown, liberar retorno tardio, chamar shutdown de novo.

**Resultado exigido:** Retorno consumido e processo/peer contido; registro não perdido.

**Evidência existente:** test_u03_cancelled_open_still_supervises_late_native_result

## AC5-02-02 — Cancelamento antes de iniciar worker

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Tentativa reservada e unidade enfileirada, sem efeito.

**Ação:** Cancelar espera/encerrar host antes do worker.

**Resultado exigido:** Guard impede spawn; liberação só após prova de não execução.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-02-03 — Cancelamento depois do spawn

**Camada:** processo real. **Estado na auditoria:** NOT_RUN.

**Preparação:** Handle de processo de laboratório registrado antes do handshake.

**Ação:** Cancelar chamador durante handshake.

**Resultado exigido:** Supervisor independente conserva handle e consegue conter a árvore.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-02-04 — Cancelamentos repetidos

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Tentativa com worker e cleanup em voo.

**Ação:** Cancelar o chamador duas vezes e o shutdown uma vez.

**Resultado exigido:** Nenhum callback órfão; ownership correto; limpeza idempotente.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-02-05 — Start nunca responde

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Thread/peer sem retorno observável.

**Ação:** Expirar orçamento e solicitar shutdown.

**Resultado exigido:** Unknown com recurso retido e limites; nada de duplicar abertura ou declarar parado.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-02-06 — Mesmo ID versus novo ID

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Abertura incerta com um slot próprio reservado.

**Ação:** Repetir ID/hash e tentar outro ID para a mesma sessão.

**Resultado exigido:** Recibo/reconciliação ou conflito; nunca segundo spawn.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-02-07 — Disposal após resultado recuperado

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Abertura tardia resolvida, sem outros trabalhos.

**Ação:** Executar shutdown/finalização pública duas vezes.

**Resultado exigido:** Pools próprios fecham apenas ao resolver; recursos do host não são fechados.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-02-08 — Restart e dados legados

**Camada:** recuperação. **Estado na auditoria:** NOT_RUN.

**Preparação:** Journal anterior contém open possivelmente iniciado, sem handle vivo no novo processo.

**Ação:** Reabrir e tentar recuperar.

**Resultado exigido:** Não reutilizar PID isolado nem executar de novo; bloquear/reconciliar com evidência de birth/owner.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-03-01 — Vinte segundos passam a zero

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Close bloqueado; primeira força só agendada para o futuro.

**Ação:** Primeiro shutdown(20,0); depois shutdown(0,0).

**Resultado exigido:** Novo prazo mínimo desperta o scheduler e a força é despachada.

**Evidência existente:** test_u04_zero_shutdown_shortens_existing_future_force

## AC5-03-02 — Expiração antecipa desligamento gracioso

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Shutdown longo em andamento.

**Ação:** Lease vence antes do prazo de força atual.

**Resultado exigido:** Atualizar para o menor prazo aplicável, sem ampliar tolerância.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-03-03 — Prazo posterior não posterga

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Força agendada urgente.

**Ação:** Chega pedido com prazo maior.

**Resultado exigido:** Prazo existente não aumenta.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-03-04 — Muitos pedidos para mesma sessão

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Força ainda aguardando ou já despachada.

**Ação:** Concorrer shutdown, revogação e close.

**Resultado exigido:** Uma tentativa lógica coalescida; não cancelar backend já iniciado.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-03-05 — Journal e observers presos

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Saturar observers e reter admit/receipt.

**Ação:** Antecipar uma força.

**Resultado exigido:** Força não espera esses recursos; sem afirmação de receipt durável inexistente.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-03-06 — Stop observado e alvo externo

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Uma sessão própria parada e uma attach externa.

**Ação:** Pedir antecipação/força repetida.

**Resultado exigido:** Nada executado na parada; attach somente desconecta; guardas de owner/generation intactas.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-04-01 — Revogação com confirmação perdida

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** SQLiteJournal real com erro explicitamente pós-commit.

**Ação:** Revogar, provar durable.revoked e tentar submit no contexto anterior.

**Resultado exigido:** Sem send_turn; memória cercada/reconciliada com row durável.

**Evidência existente:** test_u06_ambiguous_revoke_blocks_work_and_reconciles_committed_lease

## AC5-04-02 — Falha comprovada pré-entrega

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Journal devolve erro tipado com evidência de não entrega.

**Ação:** Falhar uma tentativa e repetir operação válida.

**Resultado exigido:** Reserva correta liberada; regressão T02 não volta.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-04-03 — Rollback comprovado

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Transação falha e backend comprova rollback, sem trabalho durável restante.

**Ação:** Consultar/finalizar tentativa e iniciar próxima.

**Resultado exigido:** Recuperação permitida conforme prova, não pela classe genérica Exception.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-04-04 — Renovação ambígua

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** CAS aceito, confirmação perdida; old lease tem prazo menor.

**Ação:** Tentar consumir permissões/prazo novos.

**Resultado exigido:** Não expandir antes de conciliar; old prazo/hold conservador e força preservados.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-04-05 — Callback antigo versus tentativa nova

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Tokens de tentativas diferentes; resposta atrasada anterior.

**Ação:** Entregar resposta antiga após conclusão/cancelamento lógico.

**Resultado exigido:** Callback não limpa nem aplica reserva de token diferente.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-04-06 — Commit ainda pendente e leitura antiga

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Worker retido antes do commit; leitura vê row antigo.

**Ação:** Timeout/cancelamento; consultar row; liberar worker depois.

**Resultado exigido:** Leitura antiga isolada não comprova que commit futuro é impossível.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-04-07 — Leitura de reconciliação também falha

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Resultado CAS incerto e storage indisponível.

**Ação:** Tentar trabalho e contenção.

**Resultado exigido:** Work permanece cercado; contenção independente; recurso e evidência limitados.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-04-08 — Segundo Journal conforme port

**Camada:** contrato. **Estado na auditoria:** NOT_RUN.

**Preparação:** Implementação de contrato não baseada em SQLiteJournal.

**Ação:** Executar sucesso, erro pré-entrega e ack pós-commit.

**Resultado exigido:** Runtime usa o contrato público, sem inferência por isinstance ou internals.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-05-01 — CLI Pi muda no callback

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Node+CLI válidos e prepared real.

**Ação:** Alterar CLI existente no callback de ambiente.

**Resultado exigido:** Recusar antes de start com PROFILE_DRIFT ou equivalente estável.

**Evidência existente:** test_u05_pi_launch_revalidates_non_node_artifacts[cli]

## AC5-05-02 — Dependência Pi muda no callback

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** Closure de build contém dep/index.js.

**Ação:** Alterar dep mantendo Node, package.json e cwd.

**Resultado exigido:** Mesmo bloqueio, não apenas validação de argv[0].

**Evidência existente:** test_u05_pi_launch_revalidates_non_node_artifacts[dependency]

## AC5-05-03 — Mudança depois de hash e durante fila

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Seal produzido; operação espera thread/start lock.

**Ação:** Alterar artefato selecionado e liberar.

**Resultado exigido:** Recusar atualização detectável antes do efeito, sem requalificação silenciosa.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-05-04 — Relações opcionais e peer

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Manifesto aprovado registra presença/ausência e topologia.

**Ação:** Instalar/remover uma dependência efetiva após prepare.

**Resultado exigido:** Seal inválido; escopo não passa pelo digest antigo.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-05-05 — Mudança legítima no projeto

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Build e identidade da raiz permanecem; arquivo comum do workspace muda.

**Ação:** Abrir com o mesmo contexto e perfil autorizado.

**Resultado exigido:** Não confundir conteúdo livre do projeto com troca do runtime; política explícita.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-05-06 — Custo e limites da verificação

**Camada:** carga controlada. **Estado na auditoria:** NOT_RUN.

**Preparação:** Closure próximo dos limites declarados.

**Ação:** Verificar com timers/força ativos e fila saturada.

**Resultado exigido:** I/O pesado fora do loop, worker limitado; prova de pré-spawn sem pausa ilimitada.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-06-01 — Diretório largo

**Camada:** unit/fault-injection. **Estado na auditoria:** FAIL.

**Preparação:** 1.000 arquivos reais; limite=4; contador na enumeração.

**Ação:** Iniciar scanner.

**Resultado exigido:** Recusar até observar a entrada excedente; não materializar os 1.000 nomes.

**Evidência existente:** test_u07_directory_scan_enforces_budget_during_enumeration

## AC5-06-02 — Muitos diretórios vazios

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Limite independente de diretórios/metadados.

**Ação:** Enumerar árvore sem arquivos.

**Resultado exigido:** Limite aplica durante travessia; ausência de arquivos não remove o cap.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-06-03 — Ordem determinística dentro do cap

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Mesmo conteúdo em ordens de criação diferentes.

**Ação:** Gerar manifesto em hosts/caminhos distintos.

**Resultado exigido:** Ordenação da coleção já limitada produz identidade portátil estável.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-06-04 — Symlink e especiais

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Links internos/externos, ciclo e FIFO de laboratório.

**Ação:** Enumerar layout conforme política.

**Resultado exigido:** Escapes/especiais recusados sem leitura bloqueante; ciclo/depth contabilizados.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-06-05 — Cancelamento de varredura

**Camada:** unit/fault-injection. **Estado na auditoria:** NOT_RUN.

**Preparação:** Budget cancelável com trabalho em worker.

**Ação:** Cancelar chamador e repetir scans sob cap de concorrência.

**Resultado exigido:** Sem fila/threads ilimitadas; unidade finalizada/retida de modo rastreável.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-07-01 — Wheel e sdist

**Camada:** empacotamento. **Estado na auditoria:** PASS.

**Preparação:** Cópia do snapshot, setuptools e deps identificadas.

**Ação:** Gerar artefatos sem alterar árvore auditada.

**Resultado exigido:** Artefatos válidos com SHA; não confundir build backend com qualificação de release normalizada.

**Evidência existente:** build_result.json/build.log

## AC5-07-02 — Consumidores externos

**Camada:** contrato. **Estado na auditoria:** PASS.

**Preparação:** Wheel instalado fora do checkout; subprocessos -I.

**Ação:** Executar embedded e remote sintéticos.

**Resultado exigido:** Import público e contrato passam com mesmo wheel; não equivale a dois hosts reais.

**Evidência existente:** installed_smoke.json

## AC5-07-03 — MCP HTTP direto preservado

**Camada:** integração. **Estado na auditoria:** NOT_RUN.

**Preparação:** Catálogo/imports/configuração e integrações do escopo.

**Ação:** Revisar e executar fluxo MCP entre harness e Server.

**Resultado exigido:** Core/Connector não implementam proxy ou serviço MCP; stdio nativo preservado.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-07-04 — Backend do SO e provider

**Camada:** plataforma/provider. **Estado na auditoria:** NOT_RUN.

**Preparação:** SO e versões realmente declarados qualificados.

**Ação:** Executar guardas, cancelamentos e teardown com processos/provider reais.

**Resultado exigido:** XML/logs distinguem peer de provider; nenhum skip concede PASS.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-07-05 — E2 de verdade

**Camada:** multi-host. **Estado na auditoria:** NOT_RUN.

**Preparação:** Server local sem Connector e duas máquinas para remoto.

**Ação:** Mesmo wheel em ambos; interrupção, desconexão, replay e MCP direto.

**Resultado exigido:** E2 apenas se evidenciado; ausência dos hosts vira BLOCKED.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-07-06 — Matriz rastreável

**Camada:** documental. **Estado na auditoria:** NOT_RUN.

**Preparação:** C4T-13/18/19/21/25/26/30/32/33/36/45 e U01–U07.

**Ação:** Revisar evidência exata de cada PASS.

**Resultado exigido:** Código lido e teste de outra rota não são teste executado do requisito.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.

## AC5-07-07 — Migração e decisão

**Camada:** migração. **Estado na auditoria:** NOT_RUN.

**Preparação:** Journal/API/contratos antigos e alterações C5.

**Ação:** Testar upgrade, casos incertos, repetir conformance e emitir decisão.

**Resultado exigido:** Sem reset de IDs/hashes/capabilities; E1 limitado, E2/E3 não inferidos.

**Evidência existente:** Não executado nesta auditoria; o agente deve anexar nodes, comando e resultado.
