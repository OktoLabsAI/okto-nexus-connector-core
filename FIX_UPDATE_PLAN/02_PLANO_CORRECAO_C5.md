# Plano C5 — fechamento dos gaps remanescentes de C4

**Destinatário:** agente executor do repositório `okto-nexus-connector-core`.
**Baseline auditado:** `3d304f9ccb1982f71410acb0a0622b0b8685a06f`, versão `0.2.3.dev0`.
**Status inicial:** todas as tarefas PENDING; estados dos cenários refletem apenas a auditoria descrita.
**Escopo:** 8 fases, 48 tarefas, 56 cenários; manter C4/R3/C1 como requisitos rastreados, não como planos concorrentes.

## 1. Missão e limites

Implementar e testar U01–U07 sobre o HEAD real, preservando correções posteriores. O objetivo não é propor outro plano em substituição à execução, reescrever a biblioteca nem adicionar camadas no Server/Connector. A base de adapters, journal off-loop, API pública, identidade do agente, ownership e MCP HTTP direto deve ser mantida.

É obrigatório: ausência de MCP stdio, proxy/servidor MCP ou relay MCP no Core/Connector; stdio nativo dos harnesses permitido; identidade canônica/autoridade no Server; código de runtime único no Core. Esta rodada não altera o transporte remoto nem exige implementar E2 nos outros dois repos dentro do Core.

**Invariantes:** uma operação conhecida não é reenviada; cancelamento de coroutine não prova parada de thread; efeito possivelmente iniciado conserva ownership e capacidade; recusa pré-efeito requer prova; storage/observers não podem impedir força; constatação de unknown não é autorização para abandonar um handle que pode retornar.

## 2. Leitura inicial

Ler `01_RELATORIO_REAVALIACAO.md`, este plano e `03_MATRIZ_ACEITE.md`; executar as sementes do pacote antes de editar. Ler as fases correspondentes de C4, em especial C4-02, C4-03 e C4-04. `evidencias/TRECHOS_CODIGO.md` mostra âncoras do snapshot; nomes/linhas no HEAD podem mudar.

Os dados de implementação estão em `backlog.json`; evidências de teste em `matriz_aceite.json`. DONE é status de tarefa com prova; PASS é status de cenário executado; NOT_RUN/BLOCKED não significam PASS. Corrigir a causalidade das fixtures é permitido com justificativa e diff, nunca enfraquecer a expectativa para ajustar ao defeito.

## 3. Sequência e dependências

C5-00 antes de tudo. C5-01 funda a guarda comum; C5-02 utiliza essa guarda para lifecycle de abertura. C5-03 implementa urgência no supervisor; C5-04 integra reconciliação durável. C5-05 depende de guard/open e C5-06 pode avançar em paralelo após baseline. C5-07 exige integração das demais fases. Não executar operações normais enquanto uma revogação ambígua estiver sendo “resolvida” na camada UI.

| Fase | Dependências | Achados |
|---|---|---|
| C5-00 — Estabelecer baseline, invariantes e provas | Nenhuma | U01, U02, U03, U04, U05, U06, U07 |
| C5-01 — Uma guarda por operação até o efeito nativo | C5-00 | U01, U02 |
| C5-02 — Supervisionar a abertura independentemente do chamador | C5-01 | U03, U02 |
| C5-03 — Permitir antecipação de contenção agendada | C5-00, C5-02 | U04 |
| C5-04 — CAS com resultado durável explícito e reconciliação | C5-00, C5-02, C5-03 | U06 |
| C5-05 — Selar o conjunto real de artefatos do lançamento | C5-01, C5-02 | U05 |
| C5-06 — Limitar enumeração durante a descoberta | C5-00 | U07 |
| C5-07 — Fechar evidências, contratos e entrega aos consumidores | C5-01, C5-02, C5-03, C5-04, C5-05, C5-06 | U01, U02, U03, U04, U05, U06, U07 |

## C5-00 — Estabelecer baseline, invariantes e provas

**Âncoras:** `pyproject.toml; plans/correction-c4; tests/regression/test_c4_*.py; regressoes deste pacote`.

A referência é o ZIP 3d304f9, não uma ordem para retornar a esse commit. Antes de editar, o executor confronta cada U com o HEAD e classifica: reproduzido, já corrigido com prova, mudança de fixture necessária ou bloqueado. Preservar o histórico de evidências. A rodada C4 executada no repositório contém 16 testes; as sementes originais adicionais estão neste pacote para evitar reconstrução por descrição. A adaptação de wiring do transporte é documentada, não relaxamento da asserção.

### C5-00.01 — Inventariar repositório e ambiente

**Implementar:** Registrar git rev-parse HEAD, branch, status --short, versão Python, SO, arquitetura, dependências instaladas e hashes dos arquivos de entrada. Manter alterações do usuário. Relacionar commits posteriores ao ZIP aos achados sem desfazê-los.

**Não resolver assim:** Não usar reset --hard, restaurar diretório inteiro ou declarar correção por diferença textual.

**Aceite obrigatório:** Baseline salvo; 347 hashes auditados servem como referência, não exigência de que o HEAD tenha o mesmo número de arquivos.

### C5-00.02 — Reproduzir suites com camadas distintas

**Implementar:** Executar C2/C3, as 16 C4 e test_review5.py deste pacote. Importar dependências também num subprocesso isolado. Registrar XMLs, exit code e warnings; interpretar ausência de proc_children e provider separadamente.

**Não resolver assim:** Não instalar um stub local de rfc8785 para aparentar conformance nem remover require_containment para ficar verde.

**Aceite obrigatório:** Reproduções determinísticas U01–U07 identificadas; erros de setup não classificados como defeito.

### C5-00.03 — Preservar causalidade de testes

**Implementar:** Manter autorização inicialmente válida, barreira real atingida, mutação durante espera e contagem de bytes/spawn/handle. Se assinatura mudar, adaptar fixture e anexar diff explicado. Guardas sempre fechadas desde o início não provam corrida.

**Não resolver assim:** Não xfail/skip/except amplo para esconder a regressão; não substituir serializer pelo mock que recusa antes do ponto testado.

**Aceite obrigatório:** Sementes finais mantêm condições equivalentes e possuem teardown que solta todos os locks/threads.

### C5-00.04 — Inventário completo de efeitos

**Implementar:** Criar tabela com adapter, operação, caller, filas, locks, ponto do primeiro efeito, guarda, ownership e resultado após erro. Incluir start, handshake produtivo, submit, steer, input, accept e respostas nativas, não só send_turn.

**Não resolver assim:** Não considerar todas as rotas cobertas porque um transporte possui método guard.check.

**Aceite obrigatório:** Cada rota aponta para prova de instalação e consulta da guarda na fronteira ou para indisponibilidade explícita da capacidade.

### C5-00.05 — Distinguir disponibilidade de qualificação

**Implementar:** Registrar o que os peers sintéticos demonstram e quais backends/providers requerem campanha real. Manter constraints de versão/capacidade; instalação encontrada não vira build qualificado.

**Não resolver assim:** Não elevar E0/E1 por conformance de schema ou número bruto de testes.

**Aceite obrigatório:** Escopo candidato à liberação lista SO, Python, adapter, versão e limitações com owner.

### C5-00.06 — Criar backlog rastreável

**Implementar:** Copiar backlog.json e matriz_aceite.json para plans/correction-c5; atualizar cada tarefa com commit, teste, evidência e risco. Vincular U a C4 para não criar plano concorrente que apague pendências anteriores.

**Não resolver assim:** Não marcar tarefa DONE por escrever documentação do algoritmo que ainda não executa.

**Aceite obrigatório:** As 48 tarefas e 56 cenários têm referência única; estados de implementação e de teste separados.

**Cenários da fase:** AC5-00-01, AC5-00-02, AC5-00-03, AC5-00-04. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## C5-01 — Uma guarda por operação até o efeito nativo

**Âncoras:** `native/adapter_types.py:DispatchGuards; native/runtime_bridge.py:send/reply_native_approval/open; native/adapters/{codex,pi,claude_code}.py:writer/start`.

Contrato proposto, a ser adaptado à API existente: um descritor imutável de operação contém scope do agente/binding/sessão, ID, categoria do efeito, gerações esperadas, revisão de autorização/configuração, alvo/turno/pedido esperado e referência à guarda viva. A guarda viva expõe um snapshot coerente de prazo e estado. Ler campos concorrentes sem coerência não é proteção por depender do GIL.

DispatchGuards existente pode ser reaproveitado se todas as entradas o instalarem em escopo por operação e o removerem em finally. Não usar callback global mutável compartilhado por sessões. Contextos thread-local precisam ser instalados no worker real; não são herdados implicitamente de outra thread. Cada ponto bloqueante interno que precede write/spawn exige nova validação após a espera.

| Categoria | Após prazo/revogação | Condição adicional |
|---|---|---|
| Novo trabalho, steer, input, accept | Recusar antes do efeito | Sessão, turno, pedido e geração ainda correspondem |
| Deny/cancel/interrupt | Pode continuar para conter | Não conceder trabalho; ownership e correlação continuam válidos |
| Force/observe | Não depender de lease produtiva | Handle possuído e geração/birth corretos; nunca PID isolado |
| Handshake após spawn | Pode exigir limpeza em vez de continuação | Processo já pode existir; não declarar abertura global not_sent |

A garantia é ausência de espera interna conhecida entre a checagem final e a tentativa de efeito. O SO/provider pode aceitar algo antes que uma revogação posterior seja observada: preservar resultado incerto, não prometer exatamente uma vez ou transação atômica com stdin.

### C5-01.01 — Formalizar guarda e matriz de categoria

**Implementar:** Definir descritor/port interno tipado com snapshot coerente e falha pré-efeito. Usar relógio efetivo único, sem opção que desliga a proteção no default. Separar guarda de sessão das expectativas imutáveis da operação.

**Não resolver assim:** Não substituir correlation por uma checagem apenas de deadline; não criar autorização canônica dentro do Core.

**Aceite obrigatório:** Contrato cobre revisões, prazo, draining, turno/pedido e exceções seguras para contenção.

### C5-01.02 — Corrigir replies no escritor

**Implementar:** Em reply_native_approval, instalar a guarda per-operation usada pelo writer durante toda a chamada síncrona e removê-la em finally. Transportar também correlação a revalidar depois de _write_lock. Rever pending=False anterior ao efeito: reservar pedido sem torná-lo consumido por uma escrita que não ocorreu.

**Não resolver assim:** Não só duplicar fence.check antes de reply ou marcar accept como enviado quando a guarda recusou.

**Aceite obrigatório:** U01 deadline e turno passam; deny posterior ainda funciona quando o pedido é recuperável e nenhum byte saiu.

### C5-01.03 — Levar guarda de abertura ao backend

**Implementar:** Adicionar parâmetro/porta de guarda no start interno e até o criador de processos. Consultar depois de _start_lock, preparação de ambiente/containment e quaisquer waits de bootstrap. Se o processo já foi criado, registrar handle antes de esperar o protocolo e delegar contenção ao lifecycle.

**Não resolver assim:** Não monkeypatchar funções nativas em produção nem confiar em _guarded_start antes de connector.start como fronteira final.

**Aceite obrigatório:** U02 deadline e shutdown passam usando métodos reais até spawn sentinela; caso pós-spawn produz unknown/containment e não safe refusal fictícia.

### C5-01.04 — Completar todas as rotas e adapters

**Implementar:** Aplicar o descritor em Pi/Claude e respostas/input/steer suportados. Enumerar cada chamada a write, flush, Popen/spawn e SDK equivalente. Propagar contexto em hops de thread sem permitir que uma operação sobreponha outra.

**Não resolver assim:** Não habilitar ferramenta/capability ausente só para unificar interface; não assumir que JSON-RPC igual implica mesmo lifecycle.

**Aceite obrigatório:** Inventário de C5-00 fica completo com testes próprios ou bloqueio explícito por rota.

### C5-01.05 — Preservar causalidade de erro e recibos

**Implementar:** Introduzir estados antes da primeira tentativa de byte, possível efeito e observação confirmada. Recusa anterior pode virar RuntimeCommandNotSent/EffectNotSent com código estável; depois de write parcial/flush duvidoso manter possible_effect e idempotência durável.

**Não resolver assim:** Não consultar guarda depois do write e reclassificar retroativamente como não enviado.

**Aceite obrigatório:** Fault points zero byte, parcial, flush e resposta perdida demonstram sem reenvio produtivo.

### C5-01.06 — Provar isolamento e contenção

**Implementar:** Executar barreiras nos locks reais com threads reutilizadas, alteração de geração e pedidos tardios; rodar controles positivos de envio normal. Validar força independente quando o writer está travado.

**Não resolver assim:** Não serializar o runtime inteiro com lock global durante I/O para tornar o teste verde.

**Aceite obrigatório:** AC5-01 completo na camada declarada; nenhum deadlock novo e MCP continua fora da implementação.

**Cenários da fase:** AC5-01-01, AC5-01-02, AC5-01-03, AC5-01-04, AC5-01-05, AC5-01-06, AC5-01-07, AC5-01-08, AC5-01-09, AC5-01-10, AC5-01-11, AC5-01-12. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## C5-02 — Supervisionar a abertura independentemente do chamador

**Âncoras:** `runtime.py:_OpeningAttempt/open/shutdown/_dispose_factory_if_resolved; native/runtime_bridge.py:CopiedAdapterFactory.open; ports.py:NativeFactory`.

Ampliar a tentativa existente em vez de criar outro supervisor concorrente. Campos mínimos: attempt_id, operation_key/digest, session_scope, gerações, guard, estado, Future produtor, task observadora de propriedade do Core, handle/birth quando disponível, reserva de slot, sinais de conclusão e resultado durável conhecido. O Future que cria o recurso deve ficar rastreado antes do despacho e ter um observador independente do task do cliente.

| Estado | Pode liberar recurso? | Tratamento de shutdown/cancelamento |
|---|---|---|
| RESERVED/QUEUED | Só depois de provar que não vai executar | Fechar guarda; preservar Future até conclusão/refusa |
| SPAWN_IN_FLIGHT | Não | Conservar supervisor/slot; consumir resultado tardio |
| HANDLE_KNOWN/INITIALIZING | Não, enquanto árvore existir | Guardar handle e conter sem esperar handshake infinito |
| SESSION_REGISTERED | Ownership transferido uma vez | Supervisor de sessão assume; tentativa só então resolve |
| REFUSED_PRE_EFFECT | Sim, com prova | Recibo sem efeito e término do worker comprovados |
| UNKNOWN_NO_HANDLE | Não | Reportar unknown e manter reconciliador/limites |
| STOP_OBSERVED | Conforme durabilidade necessária | Cleanup e descarte idempotentes |

Cancelar a espera do cliente não precisa significar cancelar o trabalho. O requisito é não abandonar o produtor nem seu retorno. Shutdown fecha a autorização de continuar e solicita contenção conforme o estado. Um set com session_id incerto sem vínculo ao produtor não satisfaz esse contrato.

### C5-02.01 — Criar registro de produtor e propriedade

**Implementar:** Adicionar campos da tentativa e um identificador único. Criar task/Future antes de to_thread/run_in_executor e manter referências fortes no runtime/factory conforme o port. Aguardar do cliente deve usar proteção contra cancelamento propagado ao supervisor, sem tornar espera infinita.

**Não resolver assim:** Não usar somente shield sem guardar o task e sem colher seu resultado.

**Aceite obrigatório:** Cancelamento do chamador mantém tentativa rastreável, e a contagem de aberturas não zera prematuramente.

### C5-02.02 — Colher handle cedo e tarde

**Implementar:** Registrar handle/birth tão logo spawn produza um processo, antes de handshake. Se interface atual só retorna no final, estendê-la com callback/handle de ownership restrito. Colher retorno tardio uma única vez e transferir ou conter conforme draining.

**Não resolver assim:** Não chamar close cedo e presumir que isso impediria um start que ainda nem criou recursos.

**Aceite obrigatório:** U03 passa; late result após shutdown é observado e sua contenção solicitada pelo Core.

### C5-02.03 — Separar cancelamentos e falhas

**Implementar:** Distinguir cancelamento de request, fechamento explícito do host, falha pré-spawn e perda de confirmação. Em erro, preservar unidade síncrona em voo e código causal. Tornar cleanup resistente a novo cancelamento mantendo relato honesto.

**Não resolver assim:** Não capturar BaseException e esquecer o Future após chamar close; não bloquear cliente até thread incancelável retornar.

**Aceite obrigatório:** Casos antes/depois do spawn e duas solicitações de cancelamento não abandonam owner.

### C5-02.04 — Corrigir registros, capacidade e replay

**Implementar:** Retirar tentativa de _opening somente ao transferir ownership ou resolver ausência/parada com prova. Unknown reserva capacidade e possui referências para recuperação. Mesmo ID retorna estado conhecido; outro ID para mesmo scope não cria substituto enquanto resultado incerto.

**Não resolver assim:** Não liberar slot para escapar de testes de capacidade; não importar PID salvo como comprovação de ownership.

**Aceite obrigatório:** AC5-02-05/06/08 preservam limites e histórico sem segunda abertura.

### C5-02.05 — Integrar shutdown e disposal

**Implementar:** Fechar guards de tentativas pendentes no começo de shutdown. Esperar só até orçamento, sem destruir pools necessários a late handles. Finalização pública idempotente ocorre quando produtores, sessões, forças e reconciliações dependentes resolverem.

**Não resolver assim:** Não exigir _native_factory.close() de consumidor nem fechar executor injetado pelo host sem acordo de propriedade.

**Aceite obrigatório:** U03 e testes anteriores de disposal passam; segunda chamada pública completa limpeza resolvida.

### C5-02.06 — Publicar contrato e comprovar com processo real

**Implementar:** Atualizar portas/docs e testar consumidor por wheel sem imports privados. Num SO qualificado, usar filho inofensivo que cria handle e retém handshake; cancelar chamador e comprovar controle da árvore própria.

**Não resolver assim:** Não promover sentinela running=False a evidência de backend do SO.

**Aceite obrigatório:** Relatório diferencia teste sintético, ownership real e provider real; formatos persistidos legados preservados.

**Cenários da fase:** AC5-02-01, AC5-02-02, AC5-02-03, AC5-02-04, AC5-02-05, AC5-02-06, AC5-02-07, AC5-02-08. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## C5-03 — Permitir antecipação de contenção agendada

**Âncoras:** `runtime.py:_schedule_force/_force_after_deadline/shutdown/_ForceAudit`.

A correção T01 que retirou storage do dispatch deve permanecer. Substituir a semântica “task existe, não mexer” por uma tentativa com estados WAITING, DISPATCHING, REQUESTED, OBSERVING, RESOLVED/UNKNOWN. O prazo efetivo é o mínimo dos prazos autorizados já solicitados. Enquanto WAITING, uma Event/Condition desperta o coordenador para reler o prazo. Depois de DISPATCHING não cancelar a chamada física em voo para fingir que não ocorreu.

Separar os sinais scheduler_awake, backend_dispatch_started e stop_observed. finally executado ou coroutine iniciada não é prova de que a função de força física foi alcançada. Pedidos adicionais coalescem por scope/owner_generation, sem uma thread ou timer infinito por pedido.

### C5-03.01 — Modelar tentativa e menor prazo

**Implementar:** Adicionar estado e deadline mutável com atualização curta em memória. Usar a mesma base monotônica do scheduler. immediate deve significar prazo atual mínimo, não parâmetro decorativo.

**Não resolver assim:** Não ampliar prazo por uma segunda chamada com maior tolerância.

**Aceite obrigatório:** Dois pedidos concorrentes produzem uma tentativa com prazo mínimo definido.

### C5-03.02 — Despertar espera agendada

**Implementar:** Trocar sleep único por espera em Event/Condition com timeout do deadline vigente. Atualização de prazo deve sinalizar sob política que evite lost wakeup. O scheduler relê estado depois de despertar.

**Não resolver assim:** Não cancelar e recriar indiscriminadamente task que pode já estar executando force_stop.

**Aceite obrigatório:** U04 passa sem aguardar os 20 segundos e sem que teardown dispare a força no lugar do teste.

### C5-03.03 — Distinguir dispatch de observação

**Implementar:** Registrar quando worker de força entra na função e quando backend retorna; observar parada separadamente. Manter unknown se falta prova. A resposta de shutdown zero pode ser parcial, mas não pode deixar força no deadline antigo.

**Não resolver assim:** Não usar started.set em finally como única evidência de chamada física.

**Aceite obrigatório:** Teste verifica sentinela física e, em camada SO, nascimento/parada reais.

### C5-03.04 — Coalescer motivos e manter ownership

**Implementar:** Unificar expiry, revoke, close escalado e shutdown na tentativa de força por owner. Pedidos antigos não atuam em geração nova; attach não é morto. Observers e storage não ocupam dispatch urgente.

**Não resolver assim:** Não fazer kill(pid) genérico; não repetir trabalho do agente por qualquer resultado de força.

**Aceite obrigatório:** AC5-03-02/03/04/06 passam sem multiplicar workers.

### C5-03.05 — Persistir fatos sem bloquear contenção

**Implementar:** Preservar _ForceAudit ou equivalente; rastrear tarefas limitadas, commit real, tentativas de recuperação e sinais de auditoria indisponível. Tempo menor de shutdown não inventa recibo.

**Não resolver assim:** Não recolocar await journal.admit antes do dispatch nem criar retry ilimitado em memória.

**Aceite obrigatório:** Storage retido durante toda a observação de força continua sem bloquear.

### C5-03.06 — Testar antecipação de verdade

**Implementar:** Reescrever C4T-13: primeiro agendar prazo realmente distante e provar WAITING, só então segunda solicitação zero. Adicionar observer/close presos e múltiplos deadlines. Substituir report_unknown que retorna True por leitura do relatório real.

**Não resolver assim:** Não usar um único shutdown de 0,1 segundo como prova de reagendamento.

**Aceite obrigatório:** Matriz aponta para teste com duas solicitações e barreiras; sem asserção tautológica.

**Cenários da fase:** AC5-03-01, AC5-03-02, AC5-03-03, AC5-03-04, AC5-03-05, AC5-03-06. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## C5-04 — CAS com resultado durável explícito e reconciliação

**Âncoras:** `ports.py:Journal; journal.py:cas_session_lease/get_session_lease; runtime.py:renew_lease/revoke_lease/_late_cas_applier/_apply_committed_cas`.

Não restringir o contrato implicitamente ao SQLiteJournal para explicar o defeito. O runtime deve funcionar com um Journal conforme o port público. “Transação atômica” significa commit ou rollback dos dados, não entrega infalível de uma confirmação ao chamador. O caso observado faz commit real e lança erro depois.

| Resultado comprovado | Reserva e fence | Próxima ação |
|---|---|---|
| NOT_DELIVERED | Pode liberar somente a reserva da tentativa | Retry permitido conforme autorização vigente |
| ROLLED_BACK | Liberar com prova do backend | Estado anterior ainda deve passar guardas atuais |
| COMMITTED | Aplicar row/token confirmado e revisar estado | Não reabrir sessão draining/revogada/faulted |
| UNKNOWN | Manter ownership da tentativa e bloqueio conservador | Ler estado durável e conhecer término do produtor |

Usar attempt_id/token e revisão esperada, não apenas booleano. Revogação aceita para tentativa fecha uma barreira provisória de concessão; não é necessário anunciar revogação durável antes do commit. Renovação desconhecida não amplia prazo/permissões. Ler row antigo enquanto commit ainda pode ocorrer não prova rollback. Um callback antigo não pode limpar reserva mais nova.

### C5-04.01 — Estender/clarificar contrato de resultado

**Implementar:** Definir DTO/erro tipado com fase e evidência de entrega/commit; ausência de prova é UNKNOWN. Documentar como SQLite e implementações alternativas produzem esse resultado. Reusar CoreError.possible_effect/retry_safe quando adequado sem inferir rollback de Exception.

**Não resolver assim:** Não usar cas.done(), tipo da exceção genérica ou isinstance(SQLiteJournal) como prova universal de ausência de commit.

**Aceite obrigatório:** Port possui exemplos de recusa pré-entrega, rollback comprovado e confirmação perdida pós-commit.

### C5-04.02 — Identificar cada tentativa

**Implementar:** Criar registro CAS com token, scope, expected/proposed revisions, producer Future e estado. Fazer reserva curta em memória, I/O fora de locks de segurança, finalização por token. Atualizar callbacks tardios para verificar o proprietário.

**Não resolver assim:** Não limpar pending em finally geral; não permitir resposta antiga aplicar autorização numa sessão recriada.

**Aceite obrigatório:** Mesmo sob cancelamento, apenas callback da tentativa vigente modifica sua reserva.

### C5-04.03 — Aplicar fence conservador em ambiguidade

**Implementar:** Ao aceitar revogação em andamento, impedir novas concessões pelo contexto potencialmente inválido. Resultado UNKNOWN mantém hold e permite contenção/negação. Falha segura pode remover somente o hold daquela tentativa depois de revalidar todos os demais fences.

**Não resolver assim:** Não converter hold provisório em revoked=True durável no relatório antes do commit; não liberar trabalho só porque o chamador recebeu erro.

**Aceite obrigatório:** U06 passa: depois de row revoked=True nenhum send_turn ocorre pelo contexto anterior.

### C5-04.04 — Reconciliar confirmação perdida

**Implementar:** Após erro pós-entrega, ler lease durável e resolver revisões/token junto do Future produtor. Aplicar revogação confirmada mesmo se chamada original falhou. Se leitura também falhar, manter hold e limite de tentativas, sem bloquear força.

**Não resolver assim:** Não inferir “nada aconteceu” de cancelamento; não reaplicar renewal velho sobre revogação recente.

**Aceite obrigatório:** AC5-04-04/05/06/07 passam; respostas e receipts distinguem unknown de falha segura.

### C5-04.05 — Garantir compatibilidade e armazenamento

**Implementar:** Se novos tokens exigirem colunas, fornecer migração aditiva/transacional e teste de interrupção; preservar IDs, hashes, receipts e row legados. Documentar quais linhas antigas só permitem consulta conservadora.

**Não resolver assim:** Não apagar journal/dev history nem reemitir credenciais para resolver a migração.

**Aceite obrigatório:** Upgrade/reopen não perde revogações, callbacks não apontam para token inexistente com sucesso fictício.

### C5-04.06 — Conformance com falhas nos dois lados do commit

**Implementar:** Testar SQLite real com barreiras antes da entrega, durante transação, após COMMIT e antes da resposta; segunda implementação do port deve passar. Medir que força não aguarda CAS.

**Não resolver assim:** Não demonstrar pós-commit só lançando antes de super().cas_session_lease.

**Aceite obrigatório:** U06 prova row persistida, send counter zero após fix, consulta resolve, e T02 pré-entrega continua recuperável.

**Cenários da fase:** AC5-04-01, AC5-04-02, AC5-04-03, AC5-04-04, AC5-04-05, AC5-04-06, AC5-04-07, AC5-04-08. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## C5-05 — Selar o conjunto real de artefatos do lançamento

**Âncoras:** `profiles.py:prepare_launch/verify_prepared; build_identity.py; models.py:PreparedLaunch; native/runtime_bridge.py:_launch_signature/_revalidate_content`.

A verificação final não é um novo algoritmo de autorização: ela garante que o runtime irá executar a instalação aprovada. Para Pi, isso inclui Node, launch_script, pacote e closure de dependências efetivas já considerados pela identidade de build. Observar apenas argv[0] e stat(cwd) é incompleto, mesmo sem ataque que preserve metadata.

Propor LaunchSeal versionado contendo identidade qualificada, fingerprints físicos, manifesto limitado de artefatos e referências estáveis suficientes para revalidar após callbacks/filas. Pode usar staging imutável controlado ou handles/identidades de arquivo conforme SO, desde que escopo, limpeza e segredos sejam tratados. Não é exigida eliminação universal de TOCTOU; declarar janelas residuais reais. Antes disso, cobrir mudanças ordinárias nos arquivos hoje ignorados.

Separar identidade da raiz do projeto de seu conteúdo livre. Uma alteração normal de arquivo do workspace não deve por acidente significar que Node foi atualizado. Não usar essa distinção para ignorar arquivos de configuração/plugins que realmente fazem parte do perfil executado.

### C5-05.01 — Definir todos os artefatos por adapter

**Implementar:** Extrair do prepared/manifest real a lista do que será executado/carregado: binário, CLI, dependências, configurações e hooks autorizados pertinentes. Evitar derivação limitada a argv[0]. Identificar política para arquivos opcionais que surgem depois.

**Não resolver assim:** Não transferir esse conhecimento de paths/imports para Server ou Connector.

**Aceite obrigatório:** Manifesto aponta para artefatos efetivos e identidade de raiz, sem incluir todo o disco ou todo projeto arbitrariamente.

### C5-05.02 — Produzir seal em worker limitado

**Implementar:** Gerar registro verificável depois de preparar perfil, com algoritmo/revisão e evidência de conteúdo. Fazer hashing pesado fora do event loop em capacidade limitada, com orçamento compartilhado da fase C5-06.

**Não resolver assim:** Não executar pacote desconhecido para descobrir arquivos carregados nem fazer scan sem limite para “garantir tudo”.

**Aceite obrigatório:** Seal determinístico para mesmo build e distinta evidência local para mudança de instalação.

### C5-05.03 — Revalidar após callbacks e locks

**Implementar:** Ao final de environment/resume/native_action e depois de filas relevantes, verificar seal antes do primeiro efeito. Propagar verificação leve coerente até a guarda do criador nativo; se for necessária nova leitura pesada, revalidar estado após a espera.

**Não resolver assim:** Não atualizar o snapshot para os novos bytes silenciosamente; isso autorizaria o drift em vez de recusá-lo.

**Aceite obrigatório:** U05 CLI/dependency passam, e U02 não volta por inserir uma nova espera depois da guarda.

### C5-05.04 — Tratar mudanças de layout e atualização

**Implementar:** Mudança de CLI, dependência presente/ausente, symlink ou arquivo substituído invalida o prepared. Retornar PROFILE_DRIFT estável com explicação redigida; o host faz novo prepare/approval conforme política, sem recriar identidade.

**Não resolver assim:** Não aceitar version string igual ou algoritmo antigo como fallback silencioso de qualificação.

**Aceite obrigatório:** Atualização deliberada tem fluxo claro; builds equivalentes em outra máquina continuam portáveis.

### C5-05.05 — Migrar contrato sem acoplar consumidores

**Implementar:** Adicionar campos versionados se necessário; validar prepared antigo com recusa/migração explícita antes do spawn. Publicar construtores e docs no pacote, não importar bridge privada nos hosts. Preservar dados e MCP HTTP direto.

**Não resolver assim:** Não fazer patches separados de comparação de arquivo nos dois aplicativos.

**Aceite obrigatório:** Consumidores instalados leem diagnóstico/prepare de modo público com versão fixada.

### C5-05.06 — Qualificar custo e cobertura

**Implementar:** Testar callback alterando CLI/dep, alteração em fila/start lock, e update ordinário do binário. Controlar timeouts/força em paralelo ao hashing. Requalificar provider real somente depois que build correspondente for observado.

**Não resolver assim:** Não apresentar patch de os.stat em fixture como prova de provider ou de filesystem imutável.

**Aceite obrigatório:** AC5-05 na camada declarada; custo limitado e limites/residual explicitados.

**Cenários da fase:** AC5-05-01, AC5-05-02, AC5-05-03, AC5-05-04, AC5-05-05, AC5-05-06. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## C5-06 — Limitar enumeração durante a descoberta

**Âncoras:** `build_identity.py:_iter_tree_files/_add_entry/_file_digest_counted; discovery.py; worker de prepare/verify`.

Usar enumeração incremental de diretório, contabilizando cada entrada antes de guardá-la. Ordenar apenas o conjunto já admitido e limitado ao produzir o manifesto final. Um diretório com milhões de filhos não pode produzir uma lista intermediária de milhões antes de recusar o quinto. Além de arquivos, contabilizar diretórios, metadados, profundidade, bytes e trabalho em voo. Não reutilizar cap de conteúdo como único cap de diretórios vazios.

O teste auditado usa cap=4 e 1.000 nomes; ele prova materialização antecipada, não consumo catastrófico real. A correção tem que respeitar também os caps de bytes já acertados em T07, links e arquivos especiais.

### C5-06.01 — Substituir listdir/sort eager

**Implementar:** Percorrer os.scandir ou equivalente incremental, com fechamento do iterator em todos os caminhos. Obter no máximo a entrada excedente para comprovar cap. Usar pilha/fila de diretórios também limitada.

**Não resolver assim:** Não mover sorted(listdir) para uma thread e afirmar que o limite de memória foi corrigido.

**Aceite obrigatório:** U07 passa: contagem de nomes obtidos não cresce até 1.000 para cap4.

### C5-06.02 — Compartilhar orçamento da travessia

**Implementar:** Criar Budget de arquivos, diretórios, entradas totais, profundidade e bytes do manifesto/conteúdo, aplicado inclusive a dependências e relações ausentes. Reservar orçamento antes de armazenar metadados ou abrir leitura.

**Não resolver assim:** Não reiniciar ilimitadamente um cap global para cada pacote/dir e permitir soma sem limite.

**Aceite obrigatório:** Árvore larga e muitos diretórios vazios são interrompidos incrementalmente.

### C5-06.03 — Manter determinismo sem lista ilimitada

**Implementar:** Ordenar a lista de registros somente após coleta admissível limitada. Se formato requer streaming, definir ordem e encoding determinísticos sem alterar hashes acidentalmente. Versionar só se representação mudar.

**Não resolver assim:** Não usar ordem variável de os.scandir para produzir identidade portátil distinta do mesmo build.

**Aceite obrigatório:** Mesmos bytes/topologia geram mesmo digest apesar da ordem de criação e host.

### C5-06.04 — Preservar política de arquivo

**Implementar:** Contabilizar symlink/targets, ciclos e depth; não atravessar escopo aprovado. FIFO/socket/device recusados antes de leitura. Manter validação de total projetado e bytes lidos, incluindo crescimento concorrente.

**Não resolver assim:** Não flexibilizar escape de path para fazer o scanner aceitar layout comum.

**Aceite obrigatório:** T06/T07 e casos de links/especiais passam; erro estável sem conteúdos/segredos.

### C5-06.05 — Gerenciar cancelamento e saturação

**Implementar:** Capar número de scans ativos/enfileirados; task cancelada não abandona indefinidamente unidade síncrona. Usar cancellation flag consultada entre entradas/chunks e descarte rastreado. Força usa capacidade independente.

**Não resolver assim:** Não criar nova thread por timeout nem fila de scans sem limite.

**Aceite obrigatório:** Carga sustentada com cancelamentos mantém recursos próximos dos limites declarados.

### C5-06.06 — Provar trabalho real realizado

**Implementar:** Instrumentar iteração real do SO como na semente e adicionar testes de cap exato/+1. Não medir só tamanho do resultado final. Se declarar limite de memória, anexar evidência na camada correspondente.

**Não resolver assim:** Não depender de sleep curto ou RSS sem remover referências da própria fixture.

**Aceite obrigatório:** Matriz distingue prova por contagem de entradas de campanha de memória/carga.

**Cenários da fase:** AC5-06-01, AC5-06-02, AC5-06-03, AC5-06-04, AC5-06-05. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## C5-07 — Fechar evidências, contratos e entrega aos consumidores

**Âncoras:** `plans/correction-c4/matrix.json/evidence/T01-T07.md; docs/api/lifecycle/compatibility; tools/*; pyproject.toml`.

E1 é uma decisão de escopo, não um selo concedido automaticamente por contagem de testes. Reabrir como não demonstrados os mapeamentos C4 que tratam existência de um método, teste de outra rota ou contexto sem a corrida como prova suficiente. Preservar logs antigos e adicionar correção da classificação sem apagá-los.

E0 permite integração experimental com pin exato e fakes. E1 requer garantias de autorização/ownership/contenção/configuração demonstradas no SO e modo gerenciado declarados. E2 exige os dois aplicativos reais, execução local sem Connector e fluxo remoto em dois hosts; os smokes embedded/remote deste pacote NÃO são isso. E3 exige o restante do escopo R3/C1 declarado, inclusive attach se mantido como compromisso. Não ampliar este plano para implementar os hosts por conta própria.

### C5-07.01 — Reexecutar regressões sem atalhos

**Implementar:** Rodar 10 falhas novas + controle positivo, sementes originais adaptadas e C2/C3/C4. Executar full suite em backend adequado, separando falhas ambientais e warnings. Corrigir testes cujo nome não corresponde ao setup.

**Não resolver assim:** Não somar subconjuntos duplicados ao total full nem tratar 123 falhas do sandbox como 123 causas.

**Aceite obrigatório:** XMLs e logs com comandos e commit; fixtures alteradas acompanhadas de diff e invariantes preservadas.

### C5-07.02 — Corrigir matriz e documentação

**Implementar:** Revisar C4T-13,18,19,21,25,26,30,32,33,36,45 e quaisquer alegações afetadas. Trocar PASS não demonstrado por NOT_RUN/BLOCKED ou evidência própria após fix. Explicar o que é análise estática e o que foi executado.

**Não resolver assim:** Não usar inspeção de código como substituto de race test nem escrever “todos adapters” com uma prova Codex.

**Aceite obrigatório:** Cada U e fase C5 tem aceite e status rastreável; informação anterior preservada como histórica.

### C5-07.03 — Qualificar backends e providers

**Implementar:** Executar laboratório de processos com ownership real no SO-alvo; depois provider/build qualificado nos caminhos pertinentes. Registrar versões e hashes, aprovações permitidas, interrupção e teardown. Gate indisponível recusa antes de efeito.

**Não resolver assim:** Não remover contenção Linux para contornar proc_children ausente nem herdar qualificação de campanha antiga para semântica alterada sem análise.

**Aceite obrigatório:** Escopo E1 sustentado com provas específicas; attach/outros SOs ausentes permanecem pendências.

### C5-07.04 — Empacotar e testar API instalada

**Implementar:** Gerar wheel/sdist pelo processo normalizado do repo; instalar offline fora da árvore; validar recursos, bundle, símbolos públicos, callbacks e disposal. Anexar hashes e dependências. Testar journal antigo e mudanças aditivas necessárias.

**Não resolver assim:** Não publicar PyPI/release/push sem autorização; não impor imports privados aos hosts.

**Aceite obrigatório:** Consumidores de contrato executam mesmo wheel; conformance development-partial explicitamente distinguida de normative.

### C5-07.05 — Entregar contrato ao Server e Connector

**Implementar:** Fornecer release note com assinatura de guard/factory, OpeningAttempt ownership, tratamento de erro CAS, prepared seal e shutdown parcial. Os aplicativos mantêm supervisor/loop vivo conforme estado real; não copiam adapters. Versionar mudanças antes de integrar.

**Não resolver assim:** Não adicionar MCP no Connector/Core nem transformar identidade técnica de executor em usuário Nexus.

**Aceite obrigatório:** Handoff aponta versão/hash exatos, migração, limitações, owners e plano E2 separado.

### C5-07.06 — Emitir decisão final honesta

**Implementar:** Entregar relatório por achado com commits, prova, dados residuais, testes não executados e gate. Bloquear E1 do escopo afetado se qualquer P1 demonstrado continuar; permitir preview explicitamente limitado. Arquivar riscos sem declarar cobertura universal.

**Não resolver assim:** Não terminar em “verde” com logs de provider ausente, fake ou skip interpretados como aprovação.

**Aceite obrigatório:** E0/E1/E2/E3 escolhido com critérios; resumo mostra 56 cenários planejados versus execuções efetivas, não testes inventados.

**Cenários da fase:** AC5-07-01, AC5-07-02, AC5-07-03, AC5-07-04, AC5-07-05, AC5-07-06, AC5-07-07. A matriz detalha setup, ação e resultado; relações são muitos-para-muitos e não inflacionam contagem de execução.

## 4. Guia de implementação transversal

### 4.1 Estados são contratos, não flags decorativas

O registro de tentativa precisa ser responsável por um Future real e pela transição observada. Acrescentar uma dataclass cujo conteúdo continua sendo apenas Event/closed não cumpre a fase de abertura. O token CAS precisa estar presente na finalização e reconciliação; acrescentar UUID e continuar limpando o booleano genericamente também não cumpre o plano.

Toda transição que reduz proteção verifica a revisão/owner atual e todos os outros fences. Revogação, shutdown, EOF e expiração não são “curados” por uma resposta velha de renew. Toda transição que restringe proteção pode ser aplicada em memória antes de obter storage, mas o relatório deve distinguir restrição local provisória de decisão durável confirmada.

### 4.2 Orçamento de recursos e I/O

Workers de dados, observação, força e scan têm limites declarados e filas limitadas ou coalescidas. Não criar uma thread por timeout. A consulta final de guard não pode aguardar o event loop ou adquirir a trava que o chamador mantém esperando o worker. Fazer I/O pesado em outro worker exige verificar novamente autorização e seal depois da espera; não desloca automaticamente a fronteira correta.

Guardas thread-local precisam ter escopo try/finally e nunca vazar para outra operação. Leituras compartilhadas em memória usam snapshot imutável/revisão ou lock curto coerente. Não manter locks de runtime enquanto aguarda storage/provider para tentar obter atomicidade fictícia.

### 4.3 Compatibilidade e migração

Mudanças internas podem ser livres, mas toda nova exigência ao host deve aparecer no port público e em um consumidor instalado. `PreparedLaunch` antigo não pode contornar o seal: recusar/repreparar de forma explícita. Journal antigo com operação incerta não pode ser eliminado. Quando formato de hash de build muda, versionar/requalificar sem rehash de intent/operation IDs já persistidos. Publicar notes de upgrade para Server e Connector, não corrigir cada consumidor por import privado.

### 4.4 Segurança e segredos

Testes usam projetos e credenciais artificiais. Nenhum stdout MCP é criado. Eventos de diagnóstico não contêm tokens, environment completo, respostas de aprovação sensíveis ou caminhos pessoais desnecessários. Alias/identidade do agente existente é preservado. Não usar skip-permissions ou herança irrestrita de ambiente para “simplificar” o onboarding.

## 5. Como executar e comprovar

O arquivo `regressoes/rodar.py` recebe `--repo` e `--suite`. Ele usa o Python corrente e dependências reais do projeto; não baixa ou instala nada. O executor deve criar seu ambiente de teste normal, incluindo `rfc8785==0.1.4`, `jsonschema==4.26.0` e pytest. A partir de qualquer diretório:

```bash
python caminho/do/pacote/regressoes/rodar.py --repo /caminho/okto-nexus-connector-core --suite new --out /caminho/evidencias/c5
python caminho/do/pacote/regressoes/rodar.py --repo /caminho/okto-nexus-connector-core --suite prior --out /caminho/evidencias/c5
python caminho/do/pacote/regressoes/rodar.py --repo /caminho/okto-nexus-connector-core --suite full --out /caminho/evidencias/c5
```

As mesmas opções funcionam em PowerShell com caminhos entre aspas. `new` deve falhar no baseline; depois da correção todos os seus 11 casos devem passar. `prior` preserva as sementes e casos entregues C2/C3/C4. `full` é a suíte do repo e deve ser executada em SO compatível para qualificação, não apenas neste sandbox. O runner não transforma timeout, skip ou failure em PASS.

Novos testes complementares devem ser adicionados ao repo pelo executor e vinculados à matriz. Repetir corridas com barreiras e clocks; não depender só de dormir um tempo e assumir que a operação chegou ao lock. Backend/provider reais devem ter testes separados de fixtures sintéticas.

## 6. Saída exigida do agente

Entregar: commits/diff; status por U e tarefa; tests nodes e comandos; XMLs/logs; versão/SO/Python; hashes wheel/sdist/manifest; migrações; release notes de contrato; limitações; decisão E0/E1/E2/E3 e owners de bloqueios externos. Usar `templates/EVIDENCIA.json` e `templates/RELATORIO_FINAL.md`.

A implementação não estará concluída se U01–U07 foram apenas descritos, se as sementes receberam xfail ou se mapeamentos C4 continuaram marcados PASS sem cenário equivalente. Não fazer push/publicação ou editar os outros repos sem autorização específica. A ausência de provider real pode bloquear qualificação, mas não justifica deixar uma regressão determinística corrigível sem implementação.
