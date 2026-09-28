# Plano C6 — três correções necessárias após a execução do C5

**Repositório:** okto-nexus-connector-core. **Baseline:** `df3baaf77f941485f697ff4424af17ada10b36fc`. **Versão:** `0.2.4.dev0`.
**Estado:** plano de implementação; nenhuma correção aplicada nesta auditoria.
**Contagem:** 5 fases e 27 tarefas. A matriz separada contém cenários adicionais; não são testes automaticamente implementados.

## Decisão e escopo

A revisão encontrou **três grupos de falha**, comprovados por **seis testes independentes** repetidos. V01 e V02 são P1; V03 é P2. Há ainda M01, P3, uma diferença de um nome na enumeração limitada. Não é necessária uma reescrita nem a reabertura genérica de todo o C5.

| Achado | Correção necessária | Relação com C5 |
|---|---|---|
| V01 — autorização após revogação incerta | Finalizador único, barreira de concessão e reconciliação direta/tardia | C5-04.01–06 |
| V02 — produtor/handle tardio | Ownership persiste, shutdown fecha guardas e contenção não espera close | C5-02.01–06 |
| V03 — resposta recusada antes de bytes | Reserva da aprovação não equivale a envio; negativa continua possível | C5-01.02/05/06 |
| M01 — cap+2 em vez de cap+1 | Ajuste incremental e alinhamento da semente original | C5-06 |

Preservar a identidade centrada no agente e a autoridade do Server. Harness com MCP acessa **MCP HTTP direto** no Server; Core/Connector não são servidor, cliente intermediário, fachada ou proxy MCP. Stdio de protocolos nativos continua permitido. A revisão não muda o transporte entre Server e Connector.

## Sequência de execução

C6-00 primeiro. C6-01, C6-02 e C6-03 podem avançar em áreas diferentes, mas devem concordar no estado de bloqueio e na propriedade dos recursos. Integre C6-01 e C6-02 antes de fechar shutdown. C6-04 fecha a campanha, sem depender da implementação integral de outros produtos. Trabalhar sobre o HEAD, preservando correções posteriores ao snapshot.

## Padrão de evidência

Todo teste causal começa autorizado, prova a entrada em uma barreira e só então injeta cancelamento, perda de confirmação, revogação ou expiração. Conte a escrita/entrada de spawn/handle real de laboratório. Um mock pode substituir o provider ou um erro do port, mas não a decisão que está sendo testada. Depois de bytes ou spawn possíveis, não inferir not_sent de exceção ou cancelamento. Tratar incerteza explicitamente é correto; perder o recurso que permitiria resolvê-la não é.

Este pacote já traz testes executáveis. Copie **o pacote inteiro**, incluindo `regressoes/`, e utilize `executar_verificacao.py`. Não repita a reconstrução somente a partir dos documentos Markdown.


## C6-00 — Estabelecer baseline e limites desta rodada

**Dependências:** nenhuma.

**Âncoras:** `pyproject.toml; plans/correction-c5; tests/regression/test_c5_audit.py; regressoes deste pacote`.

Esta rodada é uma continuação delimitada do C5, não uma nova arquitetura. Existem três pendências necessárias (V01–V03) e um ajuste menor de fronteira (M01). Não procurar mais problemas como condição para considerar a tarefa concluída. Não desfazer o que foi corrigido: guardas nativas de Codex/Pi/Claude, shield do produtor, antecipação da força, assinatura dos artefatos Pi, scanner incremental, journal fora do loop e MCP HTTP direto.

O snapshot auditado é df3baaf77f941485f697ff4424af17ada10b36fc; execute sobre o HEAD real sem reset. A aplicação do plano só é necessária para achados ainda reproduzíveis ou demonstrados por evidência equivalente. Um achado corrigido posteriormente exige teste e referência ao commit, não retrabalho.

### C6-00.01 — Registrar HEAD e preservar trabalho

**Implementar:** Salve branch, HEAD, git status --short, versão Python/SO, dependências e versão do pacote. Compare com df3baaf e relacione diffs posteriores aos três achados. Leia o relatório, os testes e as fases C5-01/C5-02/C5-04. Trabalhe em branch apropriada, sem alterar outros repositórios.

**Não resolver assim:** Não fazer reset --hard, restaurar o ZIP sobre o HEAD nem apagar alterações locais. Não criar contas de usuário Nexus ou transportar MCP pelo Connector.

**Aceite:** Baseline em evidencias/baseline.json; alterações prévias preservadas; diferenças conhecidas antes do primeiro patch.

### C6-00.02 — Reproduzir sem reconstruir as sementes

**Implementar:** Execute o runner do pacote com --repo. Ele inclui as seis novas parametrizações e as onze sementes C5 originais; estas últimas não estavam no pacote copiado ao repositório pelo executor anterior. Separe import/dependência/timeout de falha de produto. Registre o resultado antes de corrigir e preserve o original.

**Não resolver assim:** Não reconstruir a causa apenas pelo nome do teste; não xfail/skip/assert invertido para ficar verde; não usar stub de rfc8785.

**Aceite:** No snapshot: novas 6 FAIL; C5 entregue 11 PASS; C5 original 10 PASS + 1 FAIL menor. Mudanças posteriores podem alterar o baseline e devem ser explicadas.

### C6-00.03 — Definir dono e critério de término

**Implementar:** Dono de V01–V03 é o Core. Server e Connector recebem somente mudança pública de contrato realmente necessária. Cada tarefa precisa de teste, comando, resultado e commit. Passe primeiro as reproduções, depois os cenários correlatos da matriz.

**Não resolver assim:** Não copiar adaptações nos consumidores; não transformar E2/E3 ou suporte universal em dependência artificial para fechar estes três defeitos.

**Aceite:** Backlog com os 27 IDs preservados; requisitos C5 associados; nenhuma nova publicação/push/release sem autorização.



## C6-01 — Revogação incerta bloqueia efeitos, inclusive após cancelamento

**Dependências:** C6-00.

**Âncoras:** `runtime.py: renew_lease, revoke_lease, _reconcile_cas_error, _late_cas_applier, _apply_committed_cas, _send, native_approval, _session; native/runtime_bridge.py: EffectFence; ports.py/Journal; journal.py: CAS`.

V01 tem duas reproduções independentes com commit real de SQLite: (a) o chamador é cancelado, a revogação comita e a confirmação falha; o callback tardio limpa a reserva sem reconciliar; (b) a revogação comita, a confirmação falha e a leitura de recuperação está indisponível; pending continua true, mas submit não consulta esse bloqueio. Em ambos, revoked=True no banco e um send_turn é executado com a autorização antiga.

A correção deve ser UMA máquina de estado de atualização de lease usada pelos caminhos síncrono, timeout, cancelamento e conclusão tardia. Não adicionar apenas outra leitura ao callback. A barreira contra concessão de trabalho e a reserva de CAS são conceitos distintos; manter apenas REVOKE_BUSY para outro CAS não bloqueia submit/steer/accept/input.

| Estado da tentativa | Efeitos produtivos | Finalização |
|---|---|---|
| RESERVED_REVOKE / ENQUEUED | Bloqueados após validação e reserva da revogação | Produtor continua rastreado |
| COMMITTED_REVOKE | Bloqueados irreversivelmente na sessão | Aplicar revogação confirmada sem reabrir guardas |
| COMMITTED_RENEW | Só após confirmar estado e revalidar contexto atual | Nunca ressuscitar sessão draining/revogada/faulted |
| NOT_DELIVERED / ROLLED_BACK | Reavaliar estado vigente antes de permitir | Remover apenas a barreira pertencente à tentativa |
| UNKNOWN / RECONCILING | Não conceder efeitos dependentes da autorização incerta | Recuperação limitada; força/observação continuam disponíveis |

O hold de uma revogação validada fecha em memória antes de aguardar armazenamento. Não anuncie commit antes de comprová-lo. A incerteza sobre a lease não significa que uma nova tarefa foi executada: mantenha a causalidade de cada recibo separada. Um submit recusado antes do efeito não recebe possible_effect=True apenas porque a revogação está incerta.

### C6-01.01 — Representar tentativa identificada

**Implementar:** Crie ou complete um LeaseUpdateAttempt interno: attempt_id, scope, tipo renew/revoke, contexto esperado/proposto, versões, task produtora, estado durável, barreira de concessão e resultado da reconciliação. A flag pending pode existir como derivada, não como única autoridade. Um finalizador só pode alterar a tentativa cujo token continua atual.

**Não resolver assim:** Não usar cas.done() como prova de rollback; não deixar callbacks sem relação com uma tentativa específica; não forçar migração de banco se o estado transitório não precisar ser persistido.

**Aceite:** Dois pedidos concorrentes e callback antigo não limpam nem aplicam a tentativa nova. C5-04.02 deixa de depender de convenção verbal.

### C6-01.02 — Fechar a concessão provisoriamente

**Implementar:** Após validar identidade do agente, binding, ownership e revisão do pedido, reserve a revogação em seção crítica curta e feche uma barreira local de efeitos produtivos antes do CAS. Todos os caminhos de admissão e as guardas de writer consultam estado coerente. Preserve acesso a recibos já conhecidos e a ações seguras de contenção.

**Não resolver assim:** Não esperar get_session_lease para fechar o hold; não ampliar prazo de autorização nem usar um lock global durante SQLite ou chamada nativa; não delegar o bloqueio à UI.

**Aceite:** Durante commit incerto/read indisponível: zero novos submits, steers, accepts ou inputs no peer; deny/interrupt/force autorizados pelo escopo correto continuam possíveis.

### C6-01.03 — Unificar finalização direta e tardia

**Implementar:** Faça o callback de conclusão agendar um finalizador supervisionado comum; use o mesmo caminho após sucesso, exceção, cancelamento do chamador ou timeout. Guarde task e token enquanto o commit puder ocorrer. Recupere exceções para não gerar Task exception was never retrieved. Cancelamento do cliente só encerra a espera, não a obrigação de reconciliar.

**Não resolver assim:** Não conservar o except BaseException que limpa pending sob a premissa de que nada comitou. Não implementar recuperação apenas quando o cliente ainda aguarda.

**Aceite:** As duas parametrizações V01 passam; sucesso e erro pré-entrega dos testes históricos continuam funcionando; cancelamento não escapa do bloqueio.

### C6-01.04 — Classificar prova de resultado do Journal

**Implementar:** Especifique resultado confirmado versus indeterminado no port existente, usando DTO/erro tipado ou os campos atuais de maneira inequívoca. Uma exceção com possible_effect=True/retry_safe=False não prova ausência de commit. Compare todos os campos relevantes da linha observada: scope, owner generation, connection generation, authorization revision, configuration revision e revoked. Não aplicar contexto proposto só porque dois números coincidem.

**Não resolver assim:** Não testar isinstance(SQLiteJournal) para aceitar contratos mais fracos; não tomar uma linha antiga como rollback enquanto um produtor ainda puder comitar.

**Aceite:** Wrapper que comita e perde ACK é suportado; wrapper que rejeita antes da entrega permite finalizar com prova; row mais nova nunca é sobrescrita por memória antiga.

### C6-01.05 — Recuperar sem liberar a barreira por falha de leitura

**Implementar:** Se leitura falhar, ficar lenta ou não comprovar resultado, mantenha UNKNOWN e o bloqueio produtivo. Programe reconciliação coalescida com backoff e limite, ou publique uma retomada explícita documentada. Não criar uma tarefa de retry por chamada. Ao recuperar, aplicar somente prova compatível com a tentativa; revogação observada sempre restringe.

**Não resolver assim:** Não retornar do read error deixando submit usar contexto antigo; não obrigar outro pedido de CAS a limpar o marcador; não bloquear força atrás da recuperação.

**Aceite:** Após restaurar o storage, a mesma tentativa converge; enquanto indisponível não há send e a força chega ao backend; retries e filas permanecem limitados.

### C6-01.06 — Preservar idempotência, revisões e shutdown

**Implementar:** Deduplicação autorizada de operação já admitida continua retornando recibo mesmo durante hold. Operação nova não cruza a barreira. Shutdown marca draining e fecha todos os produtores; descarte não mata capacidade de controle usada pela reconciliação ou por processos incertos. Um CAS tardio nunca reabre uma sessão encerrando.

**Não resolver assim:** Não reutilizar ID com payload diferente; não reexecutar trabalho para descobrir se foi enviado; não marcar nova tarefa como executada para esconder a recusa.

**Aceite:** Matriz cobre commit tardio depois de shutdown, callback de tentativa antiga, retry idêntico e intenção diferente; resultado desconhecido conserva sua causalidade.

### C6-01.07 — Atualizar contrato e testes dos dois caminhos

**Implementar:** Documente REVOKE_BUSY/RECONNECT_BUSY conforme a semântica real: podem significar confirmação pendente, não necessariamente nenhum efeito durável. Quando houver código novo, atualize schema e conformance somente se ele atravessar API pública/NXL. Execute consumidor por wheel com Journal alternativo que delega commit real e injeta falha de ACK.

**Não resolver assim:** Não alterar transporte remoto, MCP ou governança canônica; não afirmar compatibilidade de novo erro sem testar serialização.

**Aceite:** Documentação, tipos e exemplos não contradizem o caso pós-commit; testes públicos não precisam importar uma factory privada.



## C6-02 — Manter ownership das aberturas e conter handles tardios

**Dependências:** C6-00.

**Âncoras:** `runtime.py: _OpeningAttempt, open/finally, shutdown, _consume_late_open, _contain_late_open, _schedule_force, _dispose_factory_if_resolved; native/runtime_bridge.py: factory/open; ledger de slots`.

V02 é uma única lacuna de lifecycle, demonstrada em três fronteiras: abertura cancelada desaparece de _opening e perde o shutdown fence; handle tardio espera close sem orçamento antes de tentar força; close/force sem STOPPED terminam a tarefa e o objeto nativo fica sem referência do Core, restando apenas um ID em _uncertain_opens.

Reaproveite o supervisor já existente. Não crie uma segunda implementação simplificada de contenção dentro de _contain_late_open. O retorno tardio deve ser transferido, uma única vez, para um registro proprietário com guarda fechada e acesso ao mesmo agendador de força/observação dos runtimes normais. Ele pode ser uma sessão técnica não produtiva ou registro comum de recurso possuído; não deve ser anunciado como pronto para trabalho.

| Marco | Registro e efeito permitido |
|---|---|
| Request deixou de esperar | Encerrar só o waiter; tentativa/produtor permanecem |
| Tentativa sem efeito e shutdown | Fechar guarda; aguardar prova de que não vai iniciar |
| Spawn possível / Future pendente | Conservar tentativa, quota e supervisão |
| Handle retornou | Registrar forte ownership ANTES de close/observe e ligar controle independente |
| Força solicitada, STOPPED ausente | Reter handle e capacidade; resultado unknown consultável |
| STOPPED observado | Encerrar recursos físicos; reconciliar ledger/recibo antes de esquecer obrigações |
| Transferência para sessão normal | Única e atômica em memória; sessão assume dono |

### C6-02.01 — Separar término do waiter de resolução da tentativa

**Implementar:** Remova o pop incondicional de _opening no finally do chamador. Use registro único por scope/attempt_id com waiter_done, producer_done e ownership_resolved separados. A task produtora, seu observador e o guard permanecem alcançáveis pelo runtime após CancelledError. Se mover para outro registro, shutdown/capacidade/disposal devem percorrê-lo explicitamente.

**Não resolver assim:** Não resolver removendo apenas o finished.set; não guardar só session_id sem vínculo à task/handle; não alterar cancelamento de request para kill indiscriminado.

**Aceite:** V02c recusa antes de spawn no adaptador Codex real quando environment é liberado depois de cancel+shutdown. Cancelamento sem shutdown segue a semântica documentada sem abandonar o resultado.

### C6-02.02 — Fechar todas as guardas pendentes no shutdown

**Implementar:** No início de shutdown, marque draining e feche os guards de todo produtor ainda não resolvido, inclusive os cujo cliente foi cancelado. A guarda já propagada ao adaptador deve continuar apontando para esse estado. Use seção curta de memória, sem storage. Não redefina deadline para uma tolerância nova ao receber handle tardio.

**Não resolver assim:** Não consultar apenas _sessions; não esperar o callback de ambiente terminar para invalidar; não passar um guard novo desconectado do produtor antigo.

**Aceite:** Prazo produtivo longo não contorna shutdown; nenhum spawn sentinela em Codex/Pi/Claude nas rotas qualificadas depois de suas esperas internas; processo já nascido segue contenção em vez de not_sent.

### C6-02.03 — Adotar o handle tardio antes de iniciar limpeza

**Implementar:** Ao colher native_task, registre o handle real com attempt/owner generation, estado não produtivo e tarefas de controle. Retenha referência forte em registro do Core antes de chamar qualquer close/observe. Transfira responsabilidade uma única vez; resultado repetido ou callback antigo não cria outro dono. Preservar referências ao Future quando ainda não houver handle.

**Não resolver assim:** Não usar só _cleanup_tasks como depósito temporário do recurso; não marcar tentativa finalizada porque a função de limpeza retornou.

**Aceite:** V02b mantém objeto vivo após coleta de lixo enquanto observe=RUNNING; consulta/recovery/segundo shutdown ainda encontram e controlam o mesmo handle.

### C6-02.04 — Usar contenção comum com orçamento independente

**Implementar:** Faça o caminho tardio delegar ao coordenador de close/force já usado pelo runtime. Inicie close gracioso em tarefa possuída, mas agende força independentemente a partir do orçamento vigente; close ou observe presos não bloqueiam a tentativa física. Preserve pool de força separado de dados/observação e storage fora do caminho crítico.

**Não resolver assim:** Não adicionar somente wait_for(close) e descartar a task de close depois do timeout; cancelamento do await não prova término da thread. Não bloquear por await observe antes de agendar força.

**Aceite:** V02a: com close retido e shutdown zero anterior, force é chamado sem liberar close. Mesmo requisito com observer retido e journal indisponível; provas observam o peer/backend, não só flag do scheduler.

### C6-02.05 — Manter recuperação enquanto a parada for desconhecida

**Implementar:** Se force falhar ou retorno/observação não provar STOPPED, mantenha estado OWNED_UNKNOWN, handle e limite de capacidade. Permita nova observação/solicitação de contenção sobre o MESMO recurso de acordo com política limitada e documentada. Não reexecutar tarefa do agente. Coalesça tentativas físicas pendentes e preserve owner token.

**Não resolver assim:** Não coletar handle porque _contain_late_open terminou; não transformar uma tentativa de force em comprovação de morte; não usar PID salvo isolado para recovery.

**Aceite:** Falha temporária de force seguida de recuperação consegue chegar a STOPPED sem novo spawn; não há coleta do objeto antes disso. Attach/external permanece intocado.

### C6-02.06 — Finalizar ledger, recibos e executores na ordem correta

**Implementar:** Após STOPPED, trate separadamente término físico, atualização do ledger e pendências duráveis. Falha de release_owned_slot mantém obrigação de reconciliação identificável; não declarar liberação durável sem confirmação. Descarte executores internos somente quando produtores, handles e controles que os usam tiverem sido resolvidos. Cancelamento repetido do shutdown não elimina o observador proprietário.

**Não resolver assim:** Não limpar _uncertain_opens no mesmo except que engole erro de release; não exigir acesso do host a _native_factory para encerrar corretamente.

**Aceite:** Segunda chamada pública de shutdown é idempotente e conclui o que se resolveu; estado incerto mantém capacidade; retorno tardio não encontra pool já descartado.

### C6-02.07 — Concluir causalidade de erro e evidência real

**Implementar:** Preserve reserva e OUTCOME_UNKNOWN se spawn pode ter ocorrido; uma recusa confirmadamente anterior libera apenas a tentativa correspondente conforme contrato. Acrescente teste em SO qualificado com filho inofensivo que segura handshake, cliente cancelado e shutdown; verificar árvore própria e token de nascimento.

**Não resolver assim:** Não promover mocks a prova de processo real; não matar alvo externo para fazer teste verde; não habilitar modo antes não qualificado.

**Aceite:** Três reproduções V02 passam e teste de processo real registra ownership/force/stop. Se o ambiente não fornecer backend, separar implementação concluída de qualificação BLOCKED.



## C6-03 — Não consumir aprovação quando a guarda recusa antes da escrita

**Dependências:** C6-00.

**Âncoras:** `native/adapters/codex.py: reply_native_approval; equivalente Claude; native/runtime_bridge.py: reply_native_approval; runtime.py: native_approval; kernel/recibos`.

V03: o novo guard protege corretamente a escrita. Porém Codex marca pending=False ANTES de reply_result. Quando a guarda recusa sob a trava nativa, nenhum byte sai; o request fica consumido e uma negativa posterior é recusada. O teste usa transporte/serializer/adapter reais, não provider.

Não remover a guarda. Substitua a interpretação binária por reserva de envio por tentativa. Identidade de RPC nunca é reutilizada para outro pedido; liberar uma reserva antes de qualquer efeito NÃO significa readmitir um novo RPC com o mesmo ID. É permitir responder ao mesmo pedido que ainda não recebeu resposta.

| Estado de resposta | Nova resposta permitida? |
|---|---|
| PENDING | Pode reservar uma tentativa para o mesmo pedido válido |
| RESERVED(token) | Não há segunda tentativa concorrente |
| REFUSED_PRE_WRITE comprovado | Reabrir o mesmo pedido se ainda ativo e token corresponde |
| WRITE_POSSIBLE / OUTCOME_UNKNOWN | Não reenviar automaticamente; manter incerteza |
| SENT | Não repetir; efeito encerrado para aquele request |
| SUPERSEDED / CANCELLED_BY_NATIVE | Não reabrir pedido antigo |

### C6-03.01 — Reservar sem consumir o pedido

**Implementar:** Sob a trava de requests, valide sessão, RPC id, request hash, method, turn e geração. Mude para RESERVED com token da tentativa, preservando o registro original. Solte a trava de estado antes de aguardar writer; a guarda per-operation já implementada continua instalada durante toda a escrita.

**Não resolver assim:** Não manter lock global durante write; não substituir pending=False por pending=True incondicional; não permitir duas respostas concorrentes.

**Aceite:** Duas respostas simultâneas não escrevem duas mensagens; nenhum pedido muda de identidade entre reserva e efeito.

### C6-03.02 — Finalizar conforme prova de bytes

**Implementar:** Se o transporte/guard retorna RuntimeCommandNotSent com prova anterior ao primeiro byte, libere só a reserva atual e preserve o pedido ativo. Se write/flush puder ter produzido bytes, mantenha resultado incerto e não restaurar retry automático. Em sucesso, marcar SENT. Revalide correlação ao finalizar: pedido cancelado/turno trocado não revive.

**Não resolver assim:** Não capturar qualquer Exception como zero bytes; não usar timeout do await como prova de ausência de envio; não marcar receipt SUCCEEDED por ter reservado.

**Aceite:** V03 passa: accept é recusado antes da escrita, depois decline gera exatamente uma resposta para o mesmo request. Partial-write/flush-error não permitem segunda resposta.

### C6-03.03 — Coordenar pedido no runtime e no adapter

**Implementar:** Alinhe pending_native_requests, o registro do adapter e o recibo da operação. O caminho EffectNotSent do runtime deve conservar o request quando o adapter também o conservou. Retry idêntico continua devolvendo seu recibo; nova decisão usa nova operação autorizada, preservando o mesmo request nativo.

**Não resolver assim:** Não reexecutar uma operação antiga com outro payload; não remover apenas o registro do adapter e deixar o runtime achar que há pedido consumido ou vice-versa.

**Aceite:** Teste público de decisão recuperável com contexto vigente verifica ambos os níveis; conformance de recibos mantém zero efeito versus possível efeito.

### C6-03.04 — Preservar controles de negativa e cobrir métodos equivalentes

**Implementar:** Negar/cancelar não concede trabalho e segue a política segura já definida no C5 para prazo produtivo vencido; ainda exigir identidade/ownership/correlação corretos. Verifique input e Claude quando utilizarem reserva equivalente. Execute casos próprios, sem anunciar Pi approval genérico não suportado.

**Não resolver assim:** Não fazer bypass geral de autorização para permitir deny; não usar renewed lease para autorizar pedido pertencente a turno antigo; não converter decline em accept.

**Aceite:** Negativa válida atinge somente o pedido correto; accept/input expirado não envia bytes; versões/métodos sem suporte continuam recusados explicitamente.

### C6-03.05 — Requalificar a matriz de aprovação

**Implementar:** Atualize C5-01.02 e AC5-01-07: o teste U01 sozinho provava zero bytes, não recuperação da negativa. Acrescente zero-byte→decline, cancelamento nativo concorrente, partial-write, retry idempotente e duas respostas. Registre metadados sem prompt/input secreto.

**Não resolver assim:** Não declarar recuperação apenas porque a primeira guarda foi consultada; não provar writer com um mock que recusa antes da trava.

**Aceite:** Tabela de efeitos contém teste por ramo; seeds U01 e o controle positivo de turno continuam passando.



## C6-04 — Ajuste menor, validação e entrega com escopo verdadeiro

**Dependências:** C6-01, C6-02, C6-03.

**Âncoras:** `build_identity.py:_iter_tree_files; plans/correction-c5; tests; pyproject; wheel e consumidores`.

M01 é uma discrepância de fronteira, NÃO retorno à enumeração ilimitada: com cap=4 são obtidos seis nomes em vez dos cinco especificados. A condição atual names_seen > cap+1 recusa no sexto. Corrigir junto da qualidade dos testes, mas não usar isso sozinho para impedir E1.

Não tratar os 123 erros da campanha Linux desta auditoria como 123 defeitos independentes: 86 são capacidade de árvore não resolvida, 24 probes sem confirmação de parada, 12 indisponibilidade de proc_children e 1 asserção de guardian sem prova de encerramento. É necessário repetir a campanha em backend compatível; estes resultados não a substituem. As seis novas reproduções são independentes desses recursos.

### C6-04.01 — Alinhar a fronteira incremental M01

**Implementar:** Recusar ao obter o primeiro nome além do orçamento documentado: após incrementar, comparar com cap, antes de append. Fechar scandir em todos os ramos. Execute a semente C5 original com 1.000 arquivos e cap=4; confirmar no máximo cinco nomes obtidos. Preserve scanner incremental, ordenação limitada e cobertura Pi.

**Não resolver assim:** Não voltar a listdir/sorted da árvore inteira; não afrouxar a semente para esconder a divergência sem revisar justificadamente o contrato.

**Aceite:** A semente original passa; pacotes dentro do limite continuam aceitos. Este ajuste não é um bloqueador de segurança isolado.

### C6-04.02 — Executar a campanha causal e reabrir evidências afetadas

**Implementar:** Execute as 6 regressões novas pelo menos duas vezes, o C5 entregue, C5 original, C2/C3/C4, unit/contract/lifecycle e suíte completa no SO qualificado. Mantenha os IDs C5; reclassifique PASS amplo quando evidência só cobre um subcaso, especialmente U06 direto versus tardio e U03 close rápido versus preso.

**Não resolver assim:** Não somar subconjuntos à suíte completa; não qualificar provider por teste sintético; não esconder warnings de fixture como se fossem necessariamente falha de produto.

**Aceite:** Cada cenário tem camada, comando, node e resultado. NOT_RUN/BLOCKED não vira PASS por compartilhar a mesma função.

### C6-04.03 — Gerar artefato e verificar consumidores externos

**Implementar:** Versione a entrega dev de acordo com a política do projeto; gere wheel/sdist e hashes. Instale fora do checkout, valide import/recursos/bundle com pin exato e execute consumers embedded/remote. Se houver alteração do port de Journal, adicione consumidor externo alternativo que demonstre ACK perdido e bloqueio correto.

**Não resolver assim:** Não chamar os exemplos sintéticos de dois hosts reais; não alterar revisão NXL sem mudança efetiva de schema; não publicar nada automaticamente.

**Aceite:** Mesmo wheel consumível por ambos; nenhuma exigência de import privado; compatibilidade de registros existentes demonstrada.

### C6-04.04 — Checar arquitetura e recuperação sem regressão

**Implementar:** Mantenha apenas configuração declarativa de cliente MCP HTTP direto; não introduzir MCP no Core/Connector, usuário Nexus ou segundo journal de domínio. Confirme que fakes não ocultam perda de ownership, erros de credencial ou duplicidade de operação. Documente qualificação de providers alterados e plataformas realmente testadas.

**Não resolver assim:** Não transferir correções de runtime para Server/Connector; não acrescentar serviço/daemon autônomo ao Core.

**Aceite:** As três fronteiras de responsabilidade permanecem; fluxo local continua sem Connector obrigatório; pendências E2/E3 possuem dono separado.

### C6-04.05 — Entregar decisão verificável

**Implementar:** Preencha template de relatório: V01/V02/V03 corrigidos ou ainda reproduzíveis, M01, testes, hashes, migrações, riscos e gate. E1 só após as garantias afetadas e backend do escopo terem prova. E2 exige hosts reais; E3 demais compromissos originais. Registre limitações sem rejeitar arbitrariamente capacidades já comprovadas.

**Não resolver assim:** Não dizer que toda arquitetura ficou pronta por seis testes verdes; não manter E1 ratificado ignorando um P1 reproduzível; não inventar outros defeitos como condição de entrega.

**Aceite:** Handoff contém artefatos e evidências, não apenas narrativa. Tarefas DONE associadas a commits e testes pertinentes.


