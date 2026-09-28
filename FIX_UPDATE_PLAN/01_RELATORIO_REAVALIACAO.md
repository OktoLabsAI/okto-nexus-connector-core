# Reavaliação do Core após o C5

**Snapshot:** `df3baaf77f941485f697ff4424af17ada10b36fc`.
**Pacote:** `0.2.4.dev0`.
**Entrada:** `okto-nexus-connector-core-main(3).zip`.
**Comparação:** baseline anterior `3d304f9`, plano C5 e suas sementes originais.

## 1. Conclusão

A atualização corrigiu a maior parte dos cenários específicos anteriores. A revisão não pressupôs que precisava encontrar outro defeito e não propõe reescrita ou uma nova arquitetura. Restaram **três grupos de correção necessária**, demonstrados por **seis testes independentes**, repetidos com o mesmo resultado. V01 e V02 são P1; V03 é P2. Há também M01, P3: um nome lido a mais na enumeração limitada. M01 sozinho não impede E1.

Não ratifico E1 nos caminhos afetados enquanto V01/V02 persistirem: revogação durável pode coexistir com novo trabalho autorizado em memória; e uma abertura cujo chamador foi cancelado pode escapar da guarda de shutdown ou perder o handle necessário à recuperação. Isso não equivale ao resultado desconhecido legítimo que preserva ownership e capacidade de controle.

O plano C6 é restrito: cinco fases, 27 tarefas, 37 cenários. Não reabre genericamente o C5. Os consumidores podem continuar integração experimental com pin, sem copiar adapters ou contornar os estados do Core.

## 2. Método e escopo

Extraí o ZIP em área de trabalho independente, comparei os arquivos com a versão anterior e li as evidências entregues pelo agente. Executei a suíte C5 reconstruída no repositório e também o `test_review5.py` original do pacote anterior. As novas regressões exercitam o Core real nas fronteiras relevantes: SQLite para commit, APIs públicas e lifecycle; Codex real até writer/spawn com recursos de laboratório. Nenhum provider real foi invocado.

Os testes usam Events/barreiras para garantir que a falha seja injetada depois que a execução realmente entrou na espera. O caso de close travado observa a ausência de força durante um intervalo delimitado enquanto a barreira continua retida; não afirma que o backend de um SO real falhou. O teste de retenção remove referências da própria fixture antes de executar coleta de lixo. O teste de spawn usa a implementação real do adapter e interrompe na primitiva de criação antes de produzir qualquer processo.

O ambiente é Linux/Python 3.13.5. rfc8785 0.1.4 não estava disponível inicialmente e a instalação pela rede falhou; usei o código oficial da tag v0.1.4, com verificação de SHA de blob de ambos os arquivos e importação em subprocesso isolado. Não foi utilizado stub. A proveniência está em `evidencias/deps_provenance.json`.

## 3. Resultados reproduzidos

| Campanha | Resultado |
|---|---|
| C5 entregue: `tests/regression/test_c5_audit.py` | **11 PASS** |
| C2/C3/C4 entregues | **44 PASS, 1 SKIP**, warning de fixture legada |
| C5 original do pacote anterior | **10 PASS, 1 FAIL** (somente M01) |
| Regressões novas C6 | **6 FAIL**, repetidas com **6 FAIL**, sem warnings na execução final |
| Suíte completa do produto | **684 PASS, 123 FAIL, 20 SKIP**, 2 warnings |
| Build wheel + sdist | PASS |
| Importação isolada do wheel | PASS |
| Verificação do bundle instalado | PASS com `development-partial` explicitamente aceito |
| Consumidores sintéticos embedded/remote usando o mesmo wheel | PASS |

As campanhas se sobrepõem. Não somar contagens dos subconjuntos às da suíte completa. As seis falhas novas são reproduções de três causas; os 37 cenários da matriz não são 37 testes já executados.

### Limite do sandbox na suíte completa

A interface de `/proc/self/task/<pid>/children` esperada pelo backend não está disponível neste ambiente. As 123 falhas se agrupam em 86 erros de capacidade retida por árvores não resolvidas, 24 probes sem confirmação de parada, 12 recusas de proc_children e uma falha de evidência de guardian. A classificação por node e assinatura está anexada. Não removi o gate de contenção e não trato essa contagem como 123 defeitos independentes.

As três pendências V foram reproduzidas sem depender desse backend. A campanha Windows/WSL2 registrada pelo executor não foi repetida aqui. Os exemplos installed embedded/remote não são os produtos Nexus Server e Connector em dois hosts. Não se pode inferir E2 deles.

## 4. Correções anteriores confirmadas e limites de interpretação

As sementes originais referentes a aprovação expirada, mudança de turno, spawn após espera, resultado tardio em caso favorável, antecipação de força, artefatos Pi e reconciliação direta do CAS passaram. O envio normal de turno continua protegido após a trava real do transporte.

A implementação passou a manter uma tarefa produtora da abertura sob `shield`, a compor a guarda de reply na escrita e a ler a lease persistida após erro direto do CAS. Esses avanços são reais. Os gaps abaixo estão nos resultados alternativos desses mesmos caminhos: retorno tardio com close travado; cancelamento seguido de shutdown; erro do callback tardio; recuperação cujo banco permanece indisponível; e restauração de pedido recusado antes de bytes.

A nova enumeração usa `scandir` incremental. A antiga materialização ilimitada foi removida. Sua diferença de fronteira é menor e não deve ser descrita como novo OOM ou scan ilimitado.

## 5. V01 — Revogação incerta não bloqueia novos efeitos em dois caminhos

**Prioridade:** P1. **Relação:** C5-04.01–06.
**Âncoras:** `runtime.py:1505–1545` (`_reconcile_cas_error`), `1620–1650` (`_late_cas_applier`), `_send`, `_session`, instalação de `EffectFence`.

### Evidência A — chamador cancelado e erro de confirmação tardio

O wrapper do Journal executa o CAS real, comita `revoked=True` e depois lança erro com `possible_effect=True` e `retry_safe=False`. Antes do commit, o chamador de revoke foi cancelado; o produtor continuou. O callback tardio encontra exceção e limpa `lease_cas_pending` sob a premissa de que não houve commit. Ele não reutiliza a reconciliação adicionada ao caminho direto.

Consulta direta ao SQLite comprovou `revoked=True`. Mesmo assim, memória permaneceu `revoked=False`, `pending=False`; um submit com contexto anterior chegou ao peer como `send_turn` e recebeu recibo `SUBMITTED`.

### Evidência B — commit aconteceu, mas a leitura de recuperação falha

No caminho direto, o mesmo commit ocorre e sua confirmação é perdida. Desta vez `get_session_lease` do Core lança erro de indisponibilidade. `_reconcile_cas_error` retorna e conserva `pending=True`, mas essa flag só bloqueia outro CAS. A admissão produtiva e a guarda do native não a tratam como hold.

O banco novamente estava `revoked=True`, enquanto a memória tinha `revoked=False`, `pending=True`; o submit antigo foi enviado.

### Alcance e correção

Não é alegação de rollback defeituoso do SQLite: a transação conclui antes da falha injetada na entrega de seu resultado pelo port público. Não é necessário supor um atacante; cancelamento, confirmação perdida e leitura indisponível são condições de recuperação já previstas pelo C5.

A correção deve unir resultado direto/tardio, separar reserva CAS de bloqueio de concessão e manter a tentativa identificada até prova suficiente. Negativa, observação e força continuam permitidas sob ownership válido. Um novo submit bloqueado não herda `possible_effect` do CAS — são operações distintas. Recibo conhecido continua consultável.

**Testes:** `test_v01_uncertain_revocation_never_allows_old_work[cancel_then_lost_ack]` e `[read_unavailable_after_commit]`.

## 6. V02 — Ownership incompleto da abertura cancelada e de seu handle tardio

**Prioridade:** P1. **Relação:** C5-02.01–06.
**Âncoras:** `runtime.py:440–535` (producer/finally), `shutdown` (guardas de `_opening`), `_consume_late_open`/`_contain_late_open` (1547–1619).

### A — close travado impede força

Depois de cancelar o waiter, o produtor devolve um native de laboratório. `_contain_late_open` faz close → observe → force → observe sequencialmente. `close()` foi retido por Event. Enquanto ele permaneceu retido, não houve entrada de força, mesmo com shutdown de orçamento zero. A força existe no peer e funcionaria se fosse chamada.

O problema não é anunciar STOPPED sem prova — o Core conserva unknown. O problema é não conseguir solicitar a contenção porque o caminho tardio não usa a independência já implementada para sessões normais.

### B — parada não comprovada e handle descartado

Em outra fixture, close retornou unknown, force levantou erro transitório e observe retornou RUNNING. Depois que a tarefa de cleanup terminou, nenhuma sessão registrada nem tarefa rastreada conservava o native. Removi as referências da fixture e executei GC: a weakref morreu, embora `_uncertain_opens` ainda contivesse o ID.

Isso comprova perda do objeto de controle disponível, não um provider real órfão. Conservar somente um ID não permite repetir força ou observar esse handle pelo port; a recuperação recebeu menos informação do que já possuía.

### C — cancelamento antes de shutdown remove a guarda do conjunto visitado

`open` remove a tentativa de `_opening` em seu finally, mesmo quando seu producer continua. `shutdown` só fecha guardas das tentativas que encontra ali. Com callback de ambiente retido, cancelei open, executei shutdown e depois liberei o callback. A factory pública, kernel, journal e adapter Codex reais chegaram a `spawn_owned_process`. A sentinela levantou erro antes de criar qualquer processo.

Essa sequência é diferente da semente antiga em que shutdown ocorria enquanto o chamador ainda estava aguardando. A guarda não falhou por prazo; o shutdown perdeu acesso à tentativa depois que seu waiter saiu.

### Correção

Waiter, producer e ownership têm vidas diferentes. Mantenha a tentativa no registro de ownership até resolução ou transferência explícita. Shutdown fecha todas as guardas ainda capazes de criar efeito, inclusive após cancelamento do waiter. Um handle tardio deve ser adotado por um registro supervisionado antes de qualquer limpeza e usar o coordenador comum de contenção. Close/observe não podem bloquear força; parada desconhecida mantém o handle forte, o slot e a possibilidade de retomada.

**Testes:** `test_v02_late_open_force_is_independent_of_hung_close`, `test_v02b_unconfirmed_late_handle_remains_owned_for_recovery`, `test_v02c_shutdown_fences_cancelled_open_before_late_start`.

## 7. V03 — Recusa comprovadamente pré-write consome pedido ainda sem resposta

**Prioridade:** P2. **Relação:** C5-01.02/05/06.
**Âncora:** `native/adapters/codex.py:1133–1169`, `reply_native_approval`.

A nova guarda recusa corretamente um accept quando a autorização vence durante o write lock. O teste conta os bytes e comprova zero. Porém, o adapter já alterou `recorded['pending'] = False` antes de chamar `reply_result`.

Uma resposta decline para o mesmo pedido, ainda correlacionado ao mesmo turno, recebe `RuntimeCommandNotSent('Native approval request ended or changed')`. Não há resposta no wire. O caminho de negativa está deliberadamente permitido após expiração, mas o registro foi consumido prematuramente.

A correção deve reservar o pedido por token, não consumi-lo antecipadamente. Recusa com prova de zero bytes permite devolver a própria reserva para PENDING somente se o pedido continua vigente. Depois de bytes/flush possíveis, não restaurar nem repetir cegamente. Alinhar estados do adapter, pending requests do Core e recibos. Rever input/elicitation e rotas equivalentes realmente suportadas.

**Teste:** `test_v03_prewrite_refused_accept_can_still_be_declined`. Usa bridge, serializer e transporte Codex reais com stdin de laboratório.

## 8. M01 — Diferença menor no orçamento da enumeração

**Prioridade:** P3, não bloqueia E1 sozinha.
**Âncora:** `build_identity.py`, `_iter_tree_files`, incremento e comparação de `names_seen`.

Com limite quatro, o original `test_u07_directory_scan_enforces_budget_during_enumeration` obteve seis nomes antes da recusa; o limite esperado era cinco, incluindo um sentinela para detectar excesso. O scanner continua incremental e limitado. A causa é comparar o contador com `cap + 1` após já consumir e incrementar, permitindo cap+2.

A correção é ajustar essa fronteira e alinhar a evidência ao comportamento, mantendo layouts com até cap válidos. Não se justifica uma mudança arquitetural, um novo scanner ou uma afirmação de exaustão de memória por esse resultado.

## 9. Qualidade e proveniência das evidências

O repositório registra que apenas quatro Markdown foram entregues ao executor anterior; ele reconstruiu as onze sementes. Elas passam. Nesta auditoria, as sementes originais foram recuperadas do ZIP anterior e dez delas também passaram. Não concluo que os testes reconstruídos sejam todos inválidos; a diferença objetiva encontrada foi M01.

O problema de qualificação está nas afirmações mais amplas: um teste de leitura bem-sucedida depois de perder ACK não comprova o caso de leitura indisponível; consumir handle com close rápido não comprova contenção com close travado; preservar escrita zero não comprova preservar o pedido para resposta negativa posterior. C6 pede evidências específicas, não mais testes apenas por volume.

As primeiras experiências locais incluíram ajustes de fixture e setup. Não estão misturadas ao resultado final: as duas execuções `review_final`/`review_final_repeat` usam o mesmo script entregue e reproduzem seis FAIL. No caso de início tardio, a fixture final utiliza o adapter Codex real até spawn sentinela, eliminando um double que poderia contornar a guarda por construção.

Os logs têm caminhos do ambiente da auditoria para proveniência. O runner entregue aceita o caminho do repositório e não depende desses caminhos fixos. Seus testes importam fixtures do próprio repositório; mudanças de API legítimas exigem adaptação documentada, não alteração da condição de falha.

## 10. Decisão e próxima ação

Implementar as 27 tarefas do plano C6, começando por V01/V02. V03 e M01 completam a rodada. A matriz contém 37 cenários: 7 FAIL observados (incluindo M01), 5 PASS delimitados, 24 NOT_RUN e 1 BLOCKED nesta campanha. Não representam 37 testes novos nem qualificação operacional universal.

Reexecutar a campanha nos ambientes que serão anunciados. E1 exige que os caminhos utilizados atendam às garantias; E2 depende dos produtos Server/Connector reais, com o mesmo wheel. Nenhum resultado sintético transforma E0 em E2. Attach ou suporte universal não são dependências artificiais para corrigir esses três grupos.

O plano não altera MCP HTTP direto, a centralidade da identidade no agente ou a separação dos três repositórios. Os 356 arquivos originais foram mantidos, e o pacote registra seus hashes e a verificação posterior. Nenhum código do produto foi corrigido, commitado ou publicado durante esta auditoria.
