# Plano complementar C8 — revisão de 0.2.6.dev0

**Destinatário:** agente executor do `okto-nexus-connector-core`.
**Snapshot auditado:** `9f0ebabcfb314f3f2da2221467d16a85134e475e`.
**Missão:** implementar X01–X03 no HEAD atual sem desfazer as correções C7.
**Estado inicial das tarefas:** PENDING. Os estados de teste da matriz são da auditoria, não do futuro código corrigido.

## Escopo e invariantes

Esta rodada tem três achados confirmados, em duas áreas. Não é uma reestruturação total. A arquitetura fica preservada: Core como biblioteca compartilhada; autoridade e identidade canônica do agente no Nexus Server; Connector como host remoto; harness com MCP acessa diretamente o Server via MCP HTTP. Nenhum MCP stdio, servidor, cliente-relay ou proxy MCP no Core/Connector. Os protocolos nativos sobre stdin/stdout continuam permitidos.

Operações conhecidas não são reenviadas para descobrir o resultado. Cancelamento de espera não comprova término de thread. A linha de lease é uma evidência de fence, não uma credencial, conjunto de permissões ou prova de vida. STOPPED e liberação durável são fatos distintos. Close/observe/storage não podem bloquear a rota física de força. Retentativa não pode produzir outra chamada física sobreposta só porque o waiter anterior foi cancelado.

O agente deve **implementar**, não responder produzindo outro plano. Preserve interfaces públicas existentes quando possível; use alterações aditivas mínimas quando necessárias. Não compense no Server ou Connector com cópias de adaptadores ou acesso a estruturas privadas.

## Evidências de partida

Leia `01_RELATORIO_REAVALIACAO.md`, `regressoes/test_c8_review.py`, `regressoes/test_c7_original.py`, a matriz e `evidencias/TRECHOS_CODIGO.md`. Rode `executar_verificacao.py`. No snapshot, C8 final dá 3 FAIL/2 PASS e C7 original dá 9 PASS. Os testes finais incluem a validação da fronteira do CAS; não usar os rascunhos preliminares.

## Estados de lease a distinguir

| Evidência da tentativa/linha | Estado produtivo | Ação |
|---|---|---|
| Commit revogado confirmado no scope | Bloqueado | Aplicar revogação; não renovar implicitamente |
| Proposta de renew confirmada e binding ainda compatível | Revalidado | Aplicar contexto autorizado da tentativa correta |
| Não entrega/rollback comprovado + linha da base exata | Revalidar | Remover só hold daquela tentativa, sem reaplicar CAS |
| Linha mais nova/incompatível com a base, CAS perdeu | Contexto antigo bloqueado | SUPERSEDED; exigir intervenção do host autorizado para encerrar/reconciliar |
| Resultado ou leitura incertos | Bloqueado para concessões dependentes | Reconciliar sem bloquear contenção; não liberar por tempo |
| Callback de tentativa antiga | Não modificar a tentativa corrente | Registrar/desconsiderar conforme token e prova |

## Estados do recurso físico e da obrigação durável

| Estado | Referências necessárias | Próxima ação |
|---|---|---|
| OPENING/resultado pendente | Future produtor, guard, slot, attempt | Aguardar/fechar guard sem abandonar produtor |
| OWNED_UNKNOWN | Handle forte e controles | Conter/observar com limites |
| FORCE_IN_FLIGHT | Future físico e owner token | Compartilhar resultado; não duplicar |
| STOPPED_RELEASE_PENDING | Prova de parada + chave exata do ledger + tentativa | Repetir/confirmar liberação, sem novo spawn nem força desnecessária |
| RELEASE_CONFIRMED | Histórico leve/recibo | Liberar recursos dispensáveis |

## Ordem de execução

C8-00 é obrigatório. C8-01 e o par C8-02/C8-03 podem avançar em paralelo. C8-02 e C8-03 devem convergir para **um mesmo registro/coordenador de recurso**, não duas rotinas paralelas que discordam sobre ownership. C8-04 fecha a campanha. Os outros repositórios podem continuar em integração experimental com pin exato; não precisam implementar as correções do Core.

## C8-00 — Baseline e conservação das correções

**Dependências:** nenhuma. **Achados:** X01, X02, X03.

A referência é o ZIP 9f0ebab, não uma ordem para fazer reset. Esta rodada só fecha três falhas comprovadas. C7 continua sendo a especificação dos comportamentos; não deve surgir um plano concorrente que reabra MCP, adaptadores ou arquitetura.

### C8-00.01 — Identificar o HEAD e o ambiente

**Implementar:** Registre git rev-parse HEAD, branch, git status --short, versão Python/SO/arquitetura, dependências e versão do pacote. Compare cada achado ao HEAD por símbolo e reprodução. Preserve alterações posteriores. Copie o ZIP completo deste pacote para uma pasta de correção, incluindo regressoes e o runner.

**Não resolver assim:** Não restaurar a árvore para o snapshot, apagar alterações ou supor que Markdown inclui os testes.

**Aceite obrigatório:** Baseline e diferenças registrados; fonte e artefato usados em cada campanha identificados.

### C8-00.02 — Reproduzir com condições causais

**Implementar:** Execute as cinco regressões C8 e as nove sementes originais C7 antes de editar. Em X01, mantenha a asserção stage=lease_cas: o teste precisa alcançar o banco, e não falhar em validação anterior. Em X03, mantenha o primeiro worker fisicamente ativo até observar a concorrência. Preserve os controles positivos.

**Não resolver assim:** Não xfail/skip, inverter assert, retirar o segundo shutdown, liberar artificialmente o worker ou usar geração fixa incompatível com a fixture.

**Aceite obrigatório:** 3 falhas/2 controles PASS no baseline, ou prova de correção já existente. Erros de fixture/setup são corrigidos e documentados, não classificados como bugs.

### C8-00.03 — Mapear as duas máquinas de estados

**Implementar:** Documente a transição de lease a partir de linha antiga/proposta/mais nova e o lifecycle único do recurso tardio. Aponte as tarefas de persistência, Future físico, capacidade reservada e caminho de recuperação. Marque W01/W04 e os cenários C7 já aprovados como preservados.

**Não resolver assim:** Não planejar reescrever toda a biblioteca; não contar documentação como correção.

**Aceite obrigatório:** Tabela de ownership e inventário de transições acompanham o diff final; cada X possui teste e tarefa relacionados.

## C8-01 — Não reabrir contexto diante de fence durável mais novo

**Dependências:** C8-00. **Achados:** X01.

Âncoras: runtime.py:renew_lease/revoke_lease, _finalize_lease_attempt, _classify_lease_row (1802–1820), _apply_lease_classification (1822–1838), _schedule_lease_reconciler e _late_cas_applier; models.py:SessionLeaseState; Journal port. Não basta mudar uma condição e manter producer_done como prova de rollback.

O cenário comprovado tem conexão local 3, proposta 4 e linha durável 5. Um segundo writer autorizado avançou o journal. A recusa STALE_GENERATION chegou do CAS real; mesmo assim, o fallback NOT_DELIVERED reabriu a concessão local. O Core não deve instalar permissões a partir da linha: ela não contém a autoridade completa. Deve recusar o contexto que agora SABE estar obsoleto.

### C8-01.01 — Conservar tentativa e evidência do produtor

**Implementar:** Materialize LeaseUpdateAttempt ou equivalente com token capturado na reserva, scope, contexto anterior completo, proposta, revisão/gerações esperadas, Future produtor e desfecho conhecido (sem entrega, rollback comprovado, commit confirmado ou incerto). Passe esse objeto/token aos finalizadores, em vez de ler o token corrente quando o callback inicia.

**Não resolver assim:** Não usar Future.done ou producer_done como sinônimo de não commit; não buscar a identidade da tentativa somente ao entrar no callback.

**Aceite obrigatório:** A classificação pode explicar de qual tentativa e de quais fatos tirou sua conclusão; callbacks velhos não modificam outra tentativa.

### C8-01.02 — Classificar a linha inteira por relação com a tentativa

**Implementar:** Compare scope, owner_generation, connection_generation, authorization_revision, configuration_revision e revoked. Defina um resultado SUPERSEDED/STALE_FENCE quando a linha for válida, mais nova ou incompatível com a base. Só use NOT_DELIVERED/ROLLED_BACK quando houver evidência suficiente de falha segura e a linha consistente corresponder à base. Linha ausente não significa, por si só, que é seguro autorizar uma sessão previamente reivindicada.

**Não resolver assim:** Não classificar toda linha não coincidente como antiga; não ler só duas revisões; não reduzir indevidamente permissões para depois recuperá-las de uma string de erro.

**Aceite obrigatório:** X01 recusa novo trabalho pelo contexto 3 ao observar geração 5; controles de falha pré-entrega antiga e renew normal continuam passando.

### C8-01.03 — Separar finalização da tentativa e validade do binding

**Implementar:** Ao constatar SUPERSEDED, finalize/resolva a tentativa conforme a prova, mas mantenha um fence produtivo do binding obsoleto. Limpar lease_cas_pending não pode limpar a invalidação de geração. Não sobrescreva a autoridade local com a linha do journal. Preserve consultas autorizadas a recibos e controles de contenção do mesmo recurso.

**Não resolver assim:** Não liberar lease_hold automaticamente para qualquer desfecho final; não exigir uma leitura SQLite em cada submit para esconder a falha; não confiar só na UI para bloquear.

**Aceite obrigatório:** Submit/steer/accept/input sob geração obsoleta têm zero efeito; a força continua alcançável; receipt conhecido não é reenviado.

### C8-01.04 — Aplicar transições coerentes e revalidar depois de awaits

**Implementar:** Use a mesma função pura de classificação no caminho direto, no callback tardio e no reconciliador. Revalide registro, token e revisão após cada leitura durável. Se outra tentativa, shutdown ou revogação fechou o recurso, não o reabra. Faça leituras fora da trava de contenção.

**Não resolver assim:** Não criar um segundo classificador mais permissivo para o retry; não segurar lock global durante SQLite; não trocar token de uma operação antiga pelo token da nova.

**Aceite obrigatório:** Testes direta/tardia/retry têm a mesma saída para os mesmos fatos; linha revogada sempre restringe; nenhuma finalização antiga remove bloqueio novo.

### C8-01.05 — Definir recuperação autorizada sem ampliar escopo

**Implementar:** Documente um estado consultável de sessão obsoleta e o erro estável usado. O host pode encerrar o recurso e abrir outro após o ciclo de ownership, ou reconciliar por uma entrada pública que valide contexto completo e geração esperada; escolha a opção compatível com o contrato existente. Se uma API aditiva for realmente necessária, publique DTO/port e atualize ambos os consumers de contrato.

**Não resolver assim:** Não aplicar automaticamente a geração 5, prazo, capabilities ou identidade a partir de metadados; não fazer spawn substituto ao receber STALE_GENERATION.

**Aceite obrigatório:** Consumidor instalado sabe que o contexto foi superado e como encerrar/reconciliar sem imports privados. Preservar identidade do agente e nenhum proxy MCP.

### C8-01.06 — Provar segurança e disponibilidade juntas

**Implementar:** Execute X01 e o controle de renew normal. Acrescente casos de linha antiga após erro comprovado, linha revoked, avanço de owner/config/auth, erro depois de commit, callback tardio e leitura indisponível. Conte writes nativos e releia o journal real. Use ao menos a concorrência de duas conexões SQLite presente na suíte atual.

**Não resolver assim:** Não trocar todas as respostas por bloqueio permanente para passar X01; não montar mock que retorna sempre revoked; não deixar o teste falhar antes de lease_cas.

**Aceite obrigatório:** Uma base antiga e comprovadamente não alterada recupera disponibilidade; uma base superada bloqueia; uma situação indeterminada não concede trabalho.

## C8-02 — Finalização durável de capacidade após STOPPED

**Dependências:** C8-00. **Achados:** X02.

Âncoras: runtime.py:_contain_late_open (1735–1747), _LateHandleRecord, _dispose_factory_if_resolved, shutdown; Journal/OwnedSlotLedger.release_owned_slot e owned_slot_page. STOPPED é um fato físico; liberação do ledger é outro fato. Não exigir nova contenção apenas porque o banco falhou, mas não apagar a obrigação durável.

### C8-02.01 — Representar obrigação de release pendente

**Implementar:** Ao observar STOPPED, registre estado técnico STOPPED_RELEASE_PENDING, com scope, opening_operation_id, owner/birth evidence pertinente, referência ao ledger, prova de parada, tentativa de liberação e erro redigido. Esse registro pode ser leve; não precisa manter o adaptador pesado para sempre.

**Não resolver assim:** Não usar só o ID em um set sem operação/ledger/evidência; não remover todos os registros e esperar que o host deduza que a quota está presa.

**Aceite obrigatório:** X02 ainda encontra obrigação quando a recusa inicial ocorre, mesmo que callbacks nativos tenham terminado.

### C8-02.02 — Finalizar somente com confirmação consistente

**Implementar:** Após sucesso confirmado de release ou leitura que prove a mesma reserva já liberada, finalize a obrigação. CoreError com efeito possível mantém dúvida e aciona consulta idempotente. Recusa pré-entrega mantém a obrigação retryable; exceção não concede sucesso. Não engolir CoreError e executar os pops incondicionais.

**Não resolver assim:** Não apagar reserva do banco manualmente, trocar o ID ou supor que um timeout prova rollback; não confundir force retornado com STOPPED.

**Aceite obrigatório:** A reserva durável só desaparece após evidência; nenhuma reserva de outro open/sessão é liberada.

### C8-02.03 — Recuperar pelo lifecycle público

**Implementar:** Inclua obrigações de release no próximo shutdown/reconcile suportado, com retry limitado e coalescido. Restaurar o ledger deve permitir concluir a mesma obrigação sem novo spawn e sem nova força sobre recurso já comprovadamente parado. Se a consulta pública existente não expõe esse estado, faça extensão aditiva mínima ou resultado documentado de shutdown.

**Não resolver assim:** Não exigir chamar _owned_slots ou editar flags privadas como procedimento de recuperação; não criar loop infinito nem tarefa por tentativa do usuário.

**Aceite obrigatório:** X02: restaurar storage e chamar lifecycle público libera a reserva; duas chamadas repetidas não produzem erro ou nova execução.

### C8-02.04 — Preservar semântica do relatório e disposal

**Implementar:** Enquanto a obrigação estiver aberta, o relatório não deve omitir a sessão como se tudo estivesse resolvido. Diferencie desconhecimento físico de pendência somente durável. Recursos de força podem ser descartados quando nenhuma operação física depender deles; o registro/worker necessário ao release continua alcançável. Revise o shutdown sem sessões para não esconder pendências.

**Não resolver assim:** Não exigir retenção ilimitada de threads já dispensáveis; não descartar a única tarefa de release ao cancelar o waiter.

**Aceite obrigatório:** Relatório e consulta indicam a pendência; após confirmação, desaparece de forma idempotente e pools dispensáveis são fechados.

### C8-02.05 — Testar limites de falha no ledger

**Implementar:** Use SQLite real e fault points antes da entrega, depois do commit e durante leitura de confirmação. Execute controle com ledger disponível, duas chamadas públicas e encerramento/reabertura do componente de ledger, preservando as restrições de prova de ownership após restart. Não faça kill a partir de registro histórico.

**Não resolver assim:** Não tratar abrir outro Core como prova de que o processo anterior morreu; não corrigir no teste chamando release privado antes da assert.

**Aceite obrigatório:** X02 e o controle passam; prova de release idempotente e nenhum efeito nativo adicional após STOPPED.

## C8-03 — Coalescência na unidade física, não só na coroutine

**Dependências:** C8-00. **Achados:** X03.

Âncoras: runtime.py:_LateHandleRecord (190–197), _contain_late_open (1673–1760), _retry_late_handles (1761–1768), shutdown/gather; native/runtime_bridge.py:force_stop/_run_force e pools. Integre esta fase com C8-02: o objetivo é UM registro proprietário e UM coordenador por recurso. Não criar uma terceira implementação de cleanup.

### C8-03.01 — Conservar controle por recurso e sua unidade física

**Implementar:** O registro comum guarda tasks/Futures de close, observe e force, incluindo a unidade síncrona quando houver thread. Identifique o handle e a tentativa de force por token. Uma coroutine cancelada cujo worker continua não libera a marca IN_FLIGHT. Faça a bridge/porta retornar ou reter a conclusão verdadeira do produtor.

**Não resolver assim:** Não considerar asyncio.Task.cancelled como término do método síncrono; não usar só force_requested sem estado de conclusão e possibilidade de retry.

**Aceite obrigatório:** Enquanto o worker original estiver ativo, o registro o identifica e protege contra outro despacho físico.

### C8-03.02 — Reutilizar/antecipar controle sem duplicar

**Implementar:** Toda chamada inicial/tardia/retry solicita contenção ao mesmo coordenador. Para WAITING, atualize o menor prazo; para DISPATCHED/IN_FLIGHT, compartilhe o resultado pendente; para retorno concluído sem parada comprovada, permita nova tentativa limitada quando necessário. Preserve força independente de close, observer e storage.

**Não resolver assim:** Não lançar nova force task por cada shutdown; não voltar a close→force sequencial; não serializar todas as sessões num lock global.

**Aceite obrigatório:** X03 mede peak=1 até terminar o primeiro worker. Um retry legítimo após falha concluída pode fazer segunda chamada, nunca sobreposta.

### C8-03.03 — Não cancelar o único produtor ao esgotar o waiter

**Implementar:** Revise wait_for(gather(...)) dos cleanups: o prazo de resposta pública encerra a espera, não a propriedade dos controles. Guarde referências supervisionadas, observe exceções e mantenha recuperação após cancelamento repetido do chamador. Use wait/shield somente onde o ownership estiver claro.

**Não resolver assim:** Não deixar orphan tasks sem dono nem capturar CancelledError e dar baixa no recurso; não multiplicar threads para compensar cancelamentos.

**Aceite obrigatório:** Shutdown curto pode retornar unknown; o primeiro controle continua supervisionado; outro shutdown não duplica enquanto ele estiver ativo.

### C8-03.04 — Aplicar quotas e liberar depois do término observado

**Implementar:** Mantenha no máximo as quantidades projetadas por recurso e o limite global dos pools/filas. Faça admission/backpressure antes de enfileirar unidades adicionais; chamadas duplicadas apenas observam a unidade existente. Término de força não é prova de morte; use observe sem promover status incorreto. Integre disposal com C8-02.

**Não resolver assim:** Não aumentar ilimitadamente pool ou usar thread por retry; não matar attach/externo para satisfazer teste; não marcar STOPPED apenas pela conclusão de force.

**Aceite obrigatório:** Carga de chamadas duplicadas não aumenta físicos em voo; recursos resolvidos são liberados; unknown conserva handle e capacidade.

### C8-03.05 — Qualificar races com peer e backend real

**Implementar:** Execute X03 mantendo gate fechado, as duas sementes W03 e os controles antigos de força após storage/pool/close travado. Adicione múltiplos shutdowns, cancelamentos e resultado perdido. Em um SO com backend disponível, use processo de laboratório com prova de nascimento.

**Não resolver assim:** Não tratar método fake chamado como qualificação do SO; não reduzir o teste a contar coroutines criadas; não remover a barreira que mantém a thread viva.

**Aceite obrigatório:** Prova unitária da coalescência física, regressões de independência verdes e campanha de backend com status honesto PASS/BLOCKED.

## C8-04 — Aceite, contratos e entrega

**Dependências:** C8-01, C8-02, C8-03. **Achados:** X01, X02, X03.

A entrega deve encerrar os três achados por evidência, sem declarar E2/E3 a partir de consumidores sintéticos. As versões e datas apresentadas pelo executor devem corresponder à campanha real, sem substituir o histórico.

### C8-04.01 — Executar matriz sem inflar contagens

**Implementar:** Rode C8 duas vezes, C7 original, regressões entregues C2–C7 e suíte completa no SO qualificado. Vincule cada cenário a test node/camada; registre falhas ambientais e testes não executados separadamente. Mantenha os controles positivos e corrija fixtures só com diff causal documentado.

**Não resolver assim:** Não somar repetição ou subconjunto ao total; não transformar skip/ausência de provider em PASS.

**Aceite obrigatório:** Matriz aponta todos os resultados; X01/X02/X03 demonstrados corrigidos sem regredir W01/W04.

### C8-04.02 — Testar wheel e compatibilidade de consumidores

**Implementar:** Construa wheel/sdist, registre hashes e instale fora da árvore. Execute exemplos embedded/remote e contratos de erro/estado público que mudar. Atualize tipos/ports/docs sem imports privados. Mudança de schema persistido só se necessária; faça migração aditiva rastreada e preserve registros unknown.

**Não resolver assim:** Não alterar hash/ID de operações antigas ou remover claims; não apresentar smoke remoto sintético como rede real.

**Aceite obrigatório:** Mesmo wheel em ambos consumidores; import público e bundle verificado; limitações de development-partial explícitas.

### C8-04.03 — Atualizar evidência de cumprimento de C7

**Implementar:** Marque C7-01.05 e C7-02.02/03/05 como complementados pela prova C8. Remova afirmações abrangentes que não apontem para testes, como coalescência física inferida da lista _cleanup_tasks. Preserve evidência histórica e explique o delta.

**Não resolver assim:** Não mover o alvo para novos requisitos não relacionados; não reabrir a lista inteira de adaptadores sem motivo.

**Aceite obrigatório:** Relatório de encerramento demonstra estados de lease, força e liberação durável; autor dos consumidores recebe apenas alterações públicas necessárias.

### C8-04.04 — Decidir liberação no escopo comprovado

**Implementar:** Declare E1 somente para combinações e garantias testadas. X01 impede validar gestão de geração enquanto contexto antigo for aceito após fence conhecido; X02/X03 devem estar resolvidos para o lifecycle declarado. E2 requer Server local e Server–Connector real; E3 exige demais compromissos. Entregue commits, diffs, testes, logs, hashes e pendências, sem publicar release sem autorização.

**Não resolver assim:** Não concluir somente porque cinco testes ficaram verdes ou porque a suíte passou em outro ambiente.

**Aceite obrigatório:** Resumo final separa implementação, regressão, qualificação de provider/SO e integração de hosts.

## Entrega mínima exigida ao terminar

Relatório que comece pelo nível efetivamente alcançado e pelo escopo de plataforma/provider. Relacione cada X a commit, diff, teste, log/XML e risco residual. Mostre o que mudou nos ports/DTOs/erros e forneça a versão exata do wheel aos dois consumidores. Anexe instruções públicas de recuperação; nenhum procedimento pode consistir em editar flags internas.

Inclua contagem por campanha e por camada, condições de timeout, warnings, hashes e resultado da verificação de integridade. Mantenha evidências de antes/depois. Declarações de qualificação que dependem de outro host ou credencial de provider permanecem separadas até execução real. Não há autorização neste plano para publicar no PyPI, fazer release público, apagar histórico ou modificar permissões de agentes.
