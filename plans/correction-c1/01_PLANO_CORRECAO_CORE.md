# Plano de correção do okto-nexus-connector-core
## Execução pelo agente responsável — auditoria 706b16a · revisão C1

**Escopo:** correção e conclusão dirigida da implementação existente, não reescrita.  
**Base auditada:** `706b16a90c54a654551519cdc357bd6fedb9427e` · pacote `nexus-connector-core 0.1.0.dev0`.  
**Especificação de arquitetura:** revisão 3, agente como identidade canônica, MCP HTTP direto ao Nexus Server.  
**Data deste plano:** 26 de setembro de 2026.  
**Estrutura:** 15 fases, 100 tarefas e 129 cenários de aceite adicionais/detalhados.  
**Estado inicial:** tarefas `PENDING`; cenários `NOT_RUN`. A elaboração deste documento não executou novamente os testes do produto nem aplicou correções.

## 1. Missão e resultado esperado

Corrigir todos os sete defeitos F01–F07 e endereçar as seis lacunas G01–G06 identificadas na auditoria, preservando a base arquitetural. Entregar uma biblioteca que os dois hosts possam consumir pela mesma API pública, com comportamento confiável diante de expiração, bloqueio de I/O, cancelamento, perda de observação, crash e recuperação.

Não basta remover as oito falhas de teste. A implementação deve sustentar as invariantes sob concorrência, com o journal real, os backends físicos e, nos gates apropriados, os providers e hosts reais. Tampouco se deve exigir que todas as plataformas/attach estejam prontas para disponibilizar um artefato incremental honesto dos modos gerenciados.

Este plano complementa e detalha R3. Nos pontos corrigidos, substitui instruções operacionais insuficientes da implementação inicial, mas não elimina requisitos R3 que ainda estão pendentes. A ausência de um item no resumo da auditoria não autoriza remover funcionalidade prevista. Decisões adicionais de implementação neste documento são requisitos propostos para a correção, não capacidades que já existiam no snapshot.

### 1.1. Ordem de leitura

Leia `00_ENTREGAR_AO_AGENTE.md`, este documento, `02_MATRIZ_REGRESSOES.md`, `03_HANDOFF_SERVER_CONNECTOR.md` e `04_GATES_E_EVIDENCIAS.md`. Consulte o relatório em `referencias/` e o plano R3 incluído. As sementes em `regressoes_originais/` reproduzem a auditoria, não substituem a matriz completa nem a API final dos testes portados.

### 1.2. Fontes e grau de comprovação

| Fonte | Uso neste plano |
|---|---|
| `referencias/RELATORIO_AUDITORIA_CORE.md` | Achados F/G, resultados históricos, limites de ambiente e anchors de código. |
| `referencias/AUDITORIA_NEXUS_CONNECTOR_CORE_706b16a.zip` | Logs, XML, hashes, trechos de fonte e sementes originais da auditoria. |
| `referencias/03_PLANO_NEXUS_CONNECTOR_CORE_R3.md` | Requisitos normativos K/TK/J e decisões MCP/identidade/ownership. |
| Snapshot do código enviado | Conferência de nomes de métodos, ports, entrypoints, contratos e scripts citados. Não representa o HEAD atual remoto. |
| Este plano C1 | Especificação de como corrigir, testar e liberar. Valores e interfaces novos são propostas a implementar. |

Os 567 PASS, 112 FAIL e 17 SKIP da suíte original e os 8 FAIL/1 PASS dirigidos pertencem à auditoria anterior. As 112 falhas foram majoritariamente efeitos da falta de comprovação de contenção no ambiente sem `/proc/.../children`, não 112 defeitos independentes demonstrados. Não copiar esses números para uma execução atual nem tratá-los como aprovação de Linux. A auditoria não executou providers reais ou hosts Windows/multi-host.

## 2. Limites arquiteturais não negociáveis

1. **Um Core reutilizável.** Os adaptadores, configuração nativa, supervisão física e contratos comuns permanecem no Core. Server e Connector não mantêm forks para contornar problemas.
2. **Identidade é do agente.** O host fornece contexto autorizado da identidade canônica do Server. Core não cria usuário Nexus, agente, chave, inbox, handoff ou regra de domínio independente.
3. **MCP só no Nexus Server, sobre HTTP(S).** Core/Connector não hospedam MCP stdio, MCP HTTP, SDK/cliente/servidor/proxy/fachada/relay. Gerar configuração do cliente do harness é permitido; intermediar chamadas MCP não.
4. **Stdio nativo continua permitido.** Codex app-server, Pi RPC e Claude stream usam seus próprios protocolos. Não remover stdin/stdout desses adaptadores por confundir transporte com MCP.
5. **Runtime local é nativo ao Server.** Server hospeda o Core sem instalar ou parear o Connector. Connector hospeda o mesmo Core em outra máquina. WSS/NXL pertence aos hosts; não é serviço do Core.
6. **Workspace físico é local ao executor.** Nenhum path remoto é resolvido pelo Server como arquivo local. O Core só usa o binding/root aprovado na sua máquina.
7. **Credenciais são referências locais e mínimas.** Não coletar chaves de centenas de agentes, herdar todo env/home ou desligar permissões para reduzir atrito. Configurar MCP HTTP direto preserva identidade e credencial válida sem rotação silenciosa.
8. **Sem efeitos exatamente uma vez prometidos.** COMMIT, thread, processo e provider não formam uma transação atômica. Preservar incerteza, idempotência de admissão e proibição de replay cego.
9. **Sem ownership inventado.** PID persistido, thread cancelada, EOF, timeout e force-stop solicitado não provam árvore terminada. Attach externo não recebe kill por stop do Core.
10. **Sem aprovação por ausência de evidência.** Capabilities, versão, plataforma e modelo efetivo são declarados conforme o que foi demonstrado. Não ligar flags nem reduzir testes para obter um status verde.

## 3. Inventário de correções e prioridades

P1 bloqueia a integração operacional do escopo afetado; P2 é exigido para a capacidade específica ou para o funcionamento sustentável e sem atrito. Isso é prioridade de execução deste plano, não classificação de vulnerabilidade externa. G06 bloqueia declarações de completude acima da evidência, não todo trabalho paralelo.

| Achado | Prioridade | Problema | Origem | Fases | Referências R3 |
|---|---|---|---|---|---|
| F01 | P1 | Lease não contém send travado | Reproduzido na auditoria | PC02; PC11 | TK-17; TK-19; TK-20 |
| F02 | P1 | Efeito começa após deadline durante persistência | Reproduzido na auditoria | PC03 | TK-16; TK-19; TK-37 |
| F03 | P1 | EOF deixa sessão aceitando trabalho | Reproduzido na auditoria | PC04 | TK-18; TK-21; TK-27 |
| F04 | P1 | SQLite síncrono bloqueia event loop | Reproduzido na auditoria | PC01 | TK-40; TK-41 |
| F05 | P1 | IDs admitidos não são reconciliáveis | Reproduzido na auditoria | PC05 | TK-05; TK-06 |
| F06 | P2 | Objetos de sessões encerradas ficam retidos | Reproduzido na auditoria | PC07 | TK-18; TK-40 |
| F07 | P2 | Modelo explícito ignorado em Codex/Claude | Reproduzido em dois testes | PC08 | TK-12; TK-21; TK-27 |
| G01 | P1 | Factory pública e Protocol inconsistentes | Inspeção do snapshot | PC06; PC14 | TK-04; TK-10; TK-41; TK-43 |
| G02 | P2 | Qualificação global atrelada ao path Pi | Inspeção + observação reproduzida | PC09 | TK-09; TK-13; TK-36 |
| G03 | P2 | Discovery de layouts incompleto | Inspeção do snapshot | PC10 | TK-11; TK-12 |
| G04 | P2 | Attach não integrado à API pública | Inspeção do snapshot | PC12 | TK-30; TK-31; TK-32 |
| G05 | P1 | Preflight/qualificação do backend insuficiente | Limitação de ambiente observada | PC02; PC11 | TK-17; TK-38 |
| G06 | P1 | Matriz e conclusão ainda parciais | Estado documental do snapshot | PC13; PC14 | TK-42; TK-43; TK-44; J01–J34 |

## 4. Sequência, dependências e paralelismo

A sequência padrão é conservadora: cada fase é concluída com os testes associados antes de liberar a fase dependente. Análise/prototipagem e preparação de testes podem avançar em paralelo, mas código não deve ser integrado sobre interfaces divergentes. O backlog JSON contém dependências de fase e uma ordem inicial de tarefas; refinar essa ordem exige preservar os gates, não remover a cobertura.

```text
PC00  baseline, contexto e regressões
 ├─ PC01  journal off-loop
 │   └─ PC02  contenção/leases independente
 │       ├─ PC03  guarda pré-efeito
 │       └─ PC04  EOF/observação
 └─ PC05  IDs, erros e legado

PC02 + PC03 + PC04 + PC05 → PC06  composição pública
PC06 → PC07  limpeza
PC06 → PC08  modelo
PC06 + PC05 → PC09  build/binding → PC10  discovery
PC02 + PC06 → PC11  backends/preflight
PC06 + PC09 + PC11 → PC12  attach (trilha própria)
PC07 + PC08 + PC09 + PC10 + PC11 → PC13  managed + integração
PC06…PC11 + PC13 → PC14  pacote e decisão de liberação
PC12 + demais pendências de R3 → gate de escopo completo E3
```

PC12 não é dependência de PC13/PC14 para uma entrega gerenciada delimitada. Isso evita esperar todo attach para experimentar o Core corrigido. Não significa remover attach do backlog nem declarar R3 completo sem ele. A publicação de previews locais pode ocorrer antes de PC14 completo: o nível de evidência deve estar declarado.

Server e Connector continuam trabalhando em suas responsabilidades. Só adotar a integração operacional após correções P1 e contrato consumível. Uma alteração necessária no host vira handoff com owner, não implementação de UI/WSS/domínio dentro do Core.

## 5. Modelo de falhas e invariantes transversais

### 5.1. Não misturar os eixos de estado

| Eixo | Exemplos de estados conceituais | O que não prova |
|---|---|---|
| Admissão | aberta, cercada, fechando | Não prova que o processo morreu. |
| Observação | stream saudável, perdido, fechamento esperado | EOF não prova turno concluído. |
| Ownership | próprio comprovado, externo, desconhecido | PID vivo não concede direito de kill. |
| Efeito | não enviado comprovado, possível, enviado, resultado observado | Timeout não transforma possível em não enviado. |
| Durabilidade | na fila, transação, commit observado, resultado incerto | Recebimento em memória não é ACK durável. |
| Qualificação | detectado, binding aprovado, build/capability qualificado | Encontrar executável não autoriza spawn. |

Esses rótulos explicam requisitos; não são enums novos obrigatórios. Reusar os modelos atuais quando comportarem a distinção. Qualquer alteração de wire exige versão/schema/fixtures/manifest e acordo com os consumidores.

### 5.2. Fronteira do efeito

```text
validar dados e contexto
    → persistir intenção/claim
    → revalidar lease/fence
    → persistir marcador de possível efeito
    → revalidar lease/fence
    → passar guarda à execução nativa
    → revalidar no ponto de despacho real (inclui atraso de thread)
    → começar spawn/write
    → observar resultado
    → persistir receipt/eventos
```

Se uma falha ocorrer depois do marcador e não for possível comprovar ausência de efeito, a conclusão conservadora é unknown. O marcador pode gerar falso positivo de incerteza no intervalo antes de spawn; isso é preferível a repetir um efeito que talvez ocorreu. Não mover o marcador para depois do efeito para reduzir falsos positivos.

Revalidar o contexto não torna possível cancelar retroativamente um byte já enviado. Se a revogação concorrer com efeito já iniciado, impedir efeitos seguintes e conter a sessão; não afirmar que a operação nunca começou. Cancelar await de `to_thread` não é autorização para liberar o recurso nem prova de que a função nativa parou.

### 5.3. Contenção e armazenamento

Ações produtivas aguardam evidência durável requerida antes de efeito. **Contenção emergencial de recurso próprio já autorizado não deve ficar bloqueada por uma nova escrita do journal.** Essa exceção deve ser pequena, documentada e testada: interromper/desligar recurso próprio; nunca spawn, novo turno, autoapprove ou takeover. Registrar intenção/motivo quando possível e manter prova preexistente de ownership. Não emitir ACK durável enquanto o banco não confirmar.

O retorno de force_stop, o signal enviado e o exit do processo principal são fatos diferentes. O aceite de stopped deve corresponder à árvore/recursos do backend qualificado, com timeout levando a unknown e retenção de slot quando não houver prova.

### 5.4. Desempenho e limites verificáveis

Não inventar SLO de produção. Antes dos testes de tempo, registrar capacidades e ocioso do runner; usar barreiras determinísticas para correção lógica e medições separadas para responsividade. Para F04, manter lock externo por mais de 350 ms e provar que timers progridem durante o lock; thread IDs e traces devem confirmar que SQL não roda no loop. Um alvo de teste como p99 inferior a 100 ms pode ser adotado apenas com runner calibrado e configuração registrada — não é promessa geral da biblioteca.

Para leases, registrar detecção, fence, grace, início de escalada e confirmação física. Bound de acionamento é função do poll/budget configurado e scheduling observado; não prometer prazo absoluto de morte de qualquer processo em qualquer SO. Não aumentar grace/timeout automaticamente até a regressão passar.

Para memória/fila, medir quantidade e bytes de cada buffer/cursor/cache, além de adapters/tasks vivos. Journal, WAL e disco têm limites diferentes; quota lógica não é quota rígida de filesystem. Testar todos os limites declarados com margem reservada para controle e políticas de backpressure reais.

### 5.5. Erros e semântica pública

Preservar códigos existentes quando equivalentes. Novos códigos abaixo são nomes propostos a formalizar no catálogo; não adicionar sem alinhar exemplos/schema/consumidores.

| Situação | Código/família esperado | Semântica mínima |
|---|---|---|
| Input inválido | VALIDATION_ERROR ou OPERATION_INVALID | Antes de admissão mutável; sem coerção silenciosa. |
| Lease/fence vencido antes de efeito | AGENT_REVOKED / STALE_GENERATION / equivalente existente | Nenhum novo efeito; não autoriza reidentificar automaticamente uma operação antiga. |
| Perda de stream | EVENT_STREAM_UNAVAILABLE | Bloqueia trabalho; não afirma processo morto nem turno completo. |
| Backend de contenção ausente | PROCESS_CONTAINMENT_UNAVAILABLE (proposta) | Retry-safe somente se nenhuma execução começou. |
| Fila/storage sem capacidade | Backpressure/StorageUnavailable tipado | Antes de enqueue pode ser seguro; request já aceito precisa reconciliação. |
| Possível efeito sem resultado | OUTCOME_UNKNOWN | possible_effect=true; não repetir automaticamente. |
| Build/capability não qualificado | NATIVE_VERSION_UNQUALIFIED / CAPABILITY_UNSUPPORTED | Sem habilitação fictícia nem fallback de modelo/execução. |
| Configuração física mudou | PROFILE_DRIFT | Requer nova seleção/aprovação pelo host; não ampliar escopo sozinho. |

Um erro é composto por code, stage, possible_effect, retry_safe, operation_id quando válido e diagnóstico redigido. Não registrar secrets, respostas de operador, prompts inteiros ou paths pessoais desnecessários em mensagens de erro. Em IDs legados inválidos no wire atual, não inserir o ID longo no campo normativo apenas para preservar aparência de erro.

## 6. Plano de implementação por fase

Os caminhos/linhas são anchors do snapshot auditado; localizar símbolos no HEAD atual. Os testes RC definidos em `02_MATRIZ_REGRESSOES.md` formam o grupo mínimo da fase. Cada tarefa herda esse gate de fase; o agente pode acrescentar associação mais fina no backlog, nunca diminuir a cobertura exigida.


### PC00 — Reconciliar o HEAD, preservar evidências e criar a campanha de regressão

**Prioridade:** P1 · **Dependências:** nenhuma · **Achados:** F01, F02, F03, F04, F05, F06, F07, G01, G02, G03, G04, G05, G06.

**Objetivo.** Estabelecer uma linha de base verificável sem assumir que o clone atual ainda é o snapshot auditado.

**Âncoras no código:** `pyproject.toml`; `plans/implementation/status.md`; `plans/implementation/matrix.md`; `tests/test_runtime.py`; `tools/consumer_smoke.py`.

**Rastreabilidade R3:** K00, K10, K11.

#### Decisões e especificação

A referência é um snapshot, não uma ordem de reset. Primeiro verificar o HEAD, alterações não commitadas, versão do pacote e alterações posteriores nos símbolos auditados. Se o commit-base não estiver no clone, comparar arquivos e registrar a limitação; não inventar um diff Git.

As oito falhas da auditoria em nove casos são resultados históricos. Não as copiar como resultado atual. O teste positivo do fingerprint Pi documenta uma propriedade local que deve continuar válida: mover a instalação muda o binding físico. A nova identidade portável de build deve ser testada à parte.

As sementes importam fixtures internas de `tests/test_runtime.py` e pressupõem `journal.close()` síncrono. A evolução para journal com lifecycle assíncrono exige portar os testes; os originais ficam preservados nesta pasta para comparação. Refatorar fixtures e sincronização é permitido, enfraquecer o comportamento exigido não.

Falhas de `/proc` devem ser categorizadas como indisponibilidade do backend naquele ambiente. Isso não as transforma automaticamente em PASS nem autoriza `xfail` em toda a suíte de processos. Usar fakes nas regressões lógicas e uma campanha separada em hosts com contenção suportada.

#### Tarefas executáveis


##### PC00.01 — Fixar a referência da intervenção

Registrar HEAD, branch, status do working tree, Python, SO/arquitetura, versão, hashes do plano e arquivos relevantes. Localizar equivalentes atuais se símbolos tiverem mudado. Não fazer reset, force push nem checkout destrutivo.

**Aceite:** Arquivo baseline.json com referência real, diferenças e arquivos preservados.


##### PC00.02 — Classificar cada achado no HEAD

Mapear F01–F07 e G01–G06 para presente, já corrigido, parcialmente corrigido ou não reproduzido. Para correção posterior, localizar teste e commit; rodar o cenário sem reverter a correção.

**Aceite:** Cada classificação contém evidência ou uma limitação explícita; nenhum achado some sem rastreabilidade.


##### PC00.03 — Portar as regressões dirigidas

Copiar as sementes para tests/regression/ ou namespace equivalente. Substituir sleeps frágeis por Events/barreiras/relógio injetável onde possível. Portar apenas a camada de fixtures para a API que será suportada. Manter os nove casos originais preservados como referência.

**Aceite:** Mapa cenário original → teste atual; 161 caracteres pode ser recusado tipadamente, mas registros antigos exigem teste adicional.


##### PC00.04 — Separar campanhas de teste

Definir grupos unitário, contrato, fault injection, processo contido, provider real, plataforma e conjunto. Não misturar campanhas que necessitam credenciais com pytest padrão. Registrar skip/BLOCKED com causa e requisito ainda não comprovado.

**Aceite:** Execução determinística funciona sem provider, rede externa nem guardian real; demais campanhas continuam exigíveis.


##### PC00.05 — Inventariar contratos e dependências

Documentar chamadas públicas usadas por Server/Connector, schemas gerados, propriedade de journal/ledger, lifecycle e relação com K/TK/J. Não presumir acesso aos outros repositórios; usar contratos de handoff quando ausentes.

**Aceite:** Mapa de impacto permite que cada consumidor saiba o que mudará e o que não deve copiar.


##### PC00.06 — Criar rastreabilidade e evidência

Instalar o backlog e a matriz deste pacote na pasta de planejamento do repositório. Para cada tarefa, guardar diff, comandos, retornos, testes e hashes. Guardar respostas de providers redigidas, nunca tokens.

**Aceite:** Nenhum estado DONE/PASS sem caminho de evidência; o plano original R3 não é sobrescrito por um resumo menos restritivo.


**Cenários mínimos desta fase:** RC-00-01, RC-00-02, RC-00-03, RC-00-04, RC-00-05.

**Gate de saída:** Inventário de divergências do HEAD, ambiente reproduzível, cobertura inicial dos achados e classificação honesta dos resultados disponíveis.


### PC01 — Remover I/O SQLite bloqueante do loop e preservar durabilidade

**Prioridade:** P1 · **Dependências:** PC00 · **Achados:** F04.

**Objetivo.** Fazer persistência, checkpoint e encerramento liberarem o event loop sem reduzir garantias de commit, CAS, ACK, quotas e recuperação.

**Âncoras no código:** `src/nexus_connector_core/journal.py:149–166,814–859`; `src/nexus_connector_core/ports.py`; `tests/test_journal_conformance.py`; `tests/test_journal_crash.py`; `tests/test_journal_disk_full.py`; `tests/test_journal_multiprocess_fairness.py`.

**Rastreabilidade R3:** K04, K10.4, K10.5, TK-16, TK-18, TK-39, TK-40.

#### Decisões e especificação

Adotar por padrão um worker dedicado por conexão de escrita: o worker abre, utiliza e fecha sua conexão. Uma alternativa é aceitável somente com a mesma disciplina de ownership, backpressure e testes. A API pública é assíncrona; a fila é limitada por quantidade e, onde payloads existem, por bytes. Proibir `check_same_thread=False` como substituto dessa disciplina.

Transação completa é uma unidade do worker; não intercalar seus statements com operações de outras tarefas. Preservar `claim_session`, CAS de lease, reserva de slots, sequenciamento de eventos, limite de armazenamento e detecção de conflito. Leitores e ledger separado também devem ser auditados: deixar um segundo SQLite síncrono no loop não resolve F04.

A chamada só confirma uma gravação durável depois do COMMIT observado. Cancelar o await de quem pediu uma transação já enfileirada não cancela automaticamente essa transação. O worker completa/rollback conforme estado real e mantém um resultado consultável; nunca lançar `InvalidStateError` ao entregar o resultado a um Future já cancelado. Exceções graves ou morte do worker bloqueiam admissões, não geram um worker substituto silencioso sobre estado incerto.

Distinguir fila normal, capacidade reservada para controles e prioridade. Uma transação já executando não pode ser preemptada pela fila urgente; por isso a contenção física de PC02 não depende de persistência urgente terminar. Fazer checkpoint/compaction em lotes limitados. Async iterators de eventos devem ler páginas via worker e liberar a transação antes de `yield`.

Introduzir `aclose()`/context manager assíncrono ou equivalente público. Se `close()` síncrono for mantido temporariamente, proibir seu uso bloqueante em event loop e documentar a transição. A vida da conexão é explícita; importar/construir descrições de opções não inicia trabalho oculto.

#### Tarefas executáveis


##### PC01.01 — Isolar a persistência em unidade serial

Extrair as operações SQL para comandos completos executados pela conexão proprietária. Preservar schema/transações existentes primeiro; evitar reescrita de schema sem necessidade. Inventariar cada chamada sqlite3 que pode bloquear.

**Aceite:** Nenhum connect/execute/commit/rollback/checkpoint/close bloqueante ocorre no loop nos caminhos operacionais.


##### PC01.02 — Implementar filas limitadas e justiça

Definir limites de requests e bytes, capacidade reservada para controles e política de fairness. Saturação antes do enqueue retorna erro tipado de backpressure, sem possível efeito; saturação após enqueue exige consulta do resultado.

**Aceite:** Métricas de profundidade/bytes e espera; carga normal não monopoliza a fila nem controles causam starvation permanente.


##### PC01.03 — Tornar cancelamento uma semântica explícita

Tratar cancelamento antes de enqueue, após enqueue, durante transação e depois do COMMIT. Guardar resultado de trabalho iniciado e entregar completion de forma thread-safe. Não executar a mesma transação de novo por timeout do chamador.

**Aceite:** Futures cancelados não quebram o worker; COMMIT incerto não é interpretado como rollback seguro.


##### PC01.04 — Preservar transações críticas

Manter admissão+claim e revisões atômicas, CAS, quotas, intent_hash, marca de efeito e recibo. Comparar traces e snapshots do journal antes/depois, incluindo journal reaberto e hosts com implementações do port.

**Aceite:** Mesmo conformance kit passa e nenhum ACK durável antecede o COMMIT.


##### PC01.05 — Cobrir leituras, ledger e manutenção

Converter leituras, storage_status, owned-slot ledger, migrations e checkpoint em acesso off-loop apropriado. Paginar eventos sem reter cursor aberto durante espera de consumidor.

**Aceite:** Não há lock prolongado por consumidor lento nem segundo banco síncrono esquecido no loop.


##### PC01.06 — Definir abertura e encerramento assíncronos

Implementar ownership explícito, drain limitado e falha tipada no fechamento. Não fechar a conexão no thread errado. Não matar arbitrariamente worker Python preso; reportar falha e impedir nova utilização do handle.

**Aceite:** Startup/shutdown repetidos não vazam threads e timeout de fechamento não declara banco encerrado sem prova.


##### PC01.07 — Instrumentar latência e pressão

Adicionar tempos de fila, transação, busy, commit e loop lag, sem dados de prompts/segredos. Testar escritor concorrente, disco lento/cheio, WAL e fila cheia.

**Aceite:** Evidências incluem responsividade e bounds, não apenas throughput.


##### PC01.08 — Migrar fixtures e exemplos

Atualizar usos de journal.close e dependências concretas. Preservar alternativas host-owned por Protocol, sem exigir herança de SQLiteJournal para implementar persistência.

**Aceite:** Dois consumidores mínimos encerram seus recursos corretamente; interfaces/documentação concordam.


**Cenários mínimos desta fase:** RC-01-01, RC-01-02, RC-01-03, RC-01-04, RC-01-05, RC-01-06, RC-01-07, RC-01-08, RC-01-09, RC-01-10.

**Gate de saída:** Conformance anterior preservado; contenção SQLite não bloqueia timers do host; cancelamento e shutdown do worker têm resultados rastreáveis.


### PC02 — Unificar contenção independente, leases e desligamento

**Prioridade:** P1 · **Dependências:** PC00, PC01 · **Achados:** F01, G05.

**Objetivo.** Impedir que um send travado, um lock ou a persistência indisponível inviabilizem a contenção de uma sessão própria sem autorização válida.

**Âncoras no código:** `src/nexus_connector_core/runtime.py:523–580,741–979,1104–1190`; `src/nexus_connector_core/native/runtime_bridge.py`; `src/nexus_connector_core/native/process`; `tests/test_session_lease_state.py`; `tests/test_owned_process.py`.

**Rastreabilidade R3:** K04, K10.1, K10.2, TK-17, TK-19, TK-20, TK-38.

#### Decisões e especificação

Separar admissão de trabalho, solicitação de desligamento, contenção física e observação do resultado. A expiração fecha imediatamente o portão de novas admissões em memória; o evento durável é registrado quando possível, mas não é pré-requisito para acionar o supervisor físico. Uma operação de contenção sobre recurso comprovadamente próprio é a exceção explícita à espera por novo commit: não pode depender de disco disponível para parar um processo perigoso.

Unificar as rotas `lease`, revoke, close, shutdown e falha do observador em um coordenador por sessão com motivo, geração, deadline e tarefas únicas. O caminho normal pode tentar interrupt/drain; a escalada forçada nunca espera indefinidamente `normal_lock`, `control_lock`, o journal, o event sink ou a coroutine nativa presa. Auditar a implementação real de `force_stop`: adicionar o método no Core não resolve se ele internamente aguardar o mesmo mutex do send.

Preservar ownership, tokens de nascimento e isolamento de árvore. O backend deve poder agir sobre o container/job/guard próprio; PID sozinho não é autorização. Para attach, o equivalente é desanexar e fechar a capacidade de controle, sem matar o processo externo.

Leases usam o relógio monotônico cercado contra rollback já adotado. O orçamento é absoluto a partir da expiração + grace; cada retry não reinicia o relógio. Renovação recebida antes da irreversibilidade da contenção segue CAS/fence; depois que a escalada iniciou não ressuscita aquela sessão. Uma revogação pendente pode bloquear trabalho local por segurança, mas só se anuncia revogação durável após CAS/COMMIT; falha do banco não autoriza afirmar sucesso global.

Não há promessa de desligamento físico garantido em prazo finito para qualquer falha de kernel/SO. Há prazo de acionamento/escalada e observação; sem confirmação, retornar `unknown`, reter slots e impedir takeover/replay. Timeout ou cancelamento da coroutine não comprova término da thread/provedor. Threads que retomam tarde precisam do fence de PC03 para não escrever novamente.

#### Tarefas executáveis


##### PC02.01 — Desenhar a máquina de estados mínima

Documentar estados de admissão, observação, ownership, contenção e resultado separados. Reusar estados existentes; tipos adicionais propostos não entram no wire sem revisão de contrato. Publicar ordem de locks e pontos em que nenhum lock pode cobrir I/O.

**Aceite:** Transições monotônicas e invariantes são exercitáveis por reducer/teste; stopped nunca deriva só de cancel().


##### PC02.02 — Fechar admissões antes de esperar I/O

Marcar expiração/revogação pendente localmente e impedir submit/steer/approval de ampliação de efeito conforme política. Leitura e contenção continuam disponíveis; persistência de evento ocorre separada.

**Aceite:** Nenhum trabalho novo aceito após fence local, mesmo se o journal estiver preso.


##### PC02.03 — Reusar coordenador único de shutdown

Extrair/reusar tarefas de força que já existem no shutdown e conectá-las à lease automática. Motivos concorrentes compartilham a mesma transição e um deadline que só pode ficar mais restritivo.

**Aceite:** Lease, stop e shutdown concorrentes não criam múltiplas árvores de tarefas nem encerram sessões novas.


##### PC02.04 — Garantir força física independente

Definir port tipada de containment/observe para sessão gerenciada; implementar nos adaptadores/process backends. A força acessa recurso próprio sem aguardar envio, parser ou lock nativo responsável pelo bloqueio.

**Aceite:** Teste com send bloqueado e close bloqueado prova acionamento do backend físico.


##### PC02.05 — Reconciliar renovação e revogação

Revalidar geração antes de iniciar a contenção, usar CAS existente e barrar renovação tardia de sessão já fechando/forçada. Distinguir fence local conservador de confirmação durável ao host.

**Aceite:** Renovação válida antes do ponto irreversível não sofre kill por watcher obsoleto; revoke confirmado não é desfeito.


##### PC02.06 — Conservar incerteza e capacidade

Só liberar slot após observação confiável da árvore própria terminada. Manter referências mínimas e evidência quando observe falha; não iniciar runtime substituto.

**Aceite:** Unknown continua ocupando capacidade contabilizada e é consultável.


##### PC02.07 — Cobrir ações de segurança sem journal saudável

Implementar registro best-effort redigido de contenção e consolidação posterior. Manter marcadores duráveis prévios de nascimento/efeito. Não confirmar novos efeitos enquanto storage está indisponível.

**Aceite:** Falha de disco não paralisa contenção; log volátil não é apresentado como ACK durável.


##### PC02.08 — Publicar política e métricas

Expor configuração com limites validados, instante de fence, motivo, solicitação de força, observação e budget esgotado. Não alterar defaults silenciosamente para fazer teste passar.

**Aceite:** Evidência reporta detecção/escalada/observação separadamente; API não promete tempo real rígido.


**Cenários mínimos desta fase:** RC-02-01, RC-02-02, RC-02-03, RC-02-04, RC-02-05, RC-02-06, RC-02-07, RC-02-08, RC-02-09, RC-02-10, RC-02-11.

**Gate de saída:** Expiração e revogação acionam contenção com send/storage travados; sem kill externo, sucesso fictício ou liberação prematura de slots.


### PC03 — Revalidar autorização na fronteira real do efeito

**Prioridade:** P1 · **Dependências:** PC01, PC02 · **Achados:** F02.

**Objetivo.** Nenhum novo spawn ou write começa usando autorização já expirada/revogada enquanto a operação aguardava persistência ou execução nativa.

**Âncoras no código:** `src/nexus_connector_core/kernel.py:20–80`; `src/nexus_connector_core/runtime.py`; `src/nexus_connector_core/native/runtime_bridge.py`; `tests/test_kernel.py`; `tests/test_native_prewrite_adapters.py`.

**Rastreabilidade R3:** K04.1, K04.4, K10.1, TK-16, TK-19, TK-37.

#### Decisões e especificação

Preservar intenção e marca de possível efeito antes de despachar o efeito. Revalidar após `admit`, após `mark_possible_effect` e imediatamente antes da invocação, usando a lease e o fence atual — não somente o `ExecutionContext` imutável recebido originalmente.

O kernel hoje recebe callback sem um contrato explícito de pré-write. Introduzir uma guarda compartilhada por sessão/operação, tipada e consumida pelo adaptador. Nome e assinatura são decisões da implementação; os requisitos são identidade/namespace, ação, deadline monotônico, geração de owner/conexão, revisões aplicáveis e latch de contenção. O host continua sendo quem autoriza; o Core apenas aplica/revalida o contexto concedido, não consulta cadastros nem cria políticas.

A checagem no loop não basta quando o callback usa `asyncio.to_thread`: a thread pode iniciar mais tarde. Fazer verificação no ponto mais próximo do spawn/write efetivo. Projetar uma região crítica curta entre validar e marcar o despacho como iniciado; ela não pode reter lock de segurança durante I/O bloqueante. Revogação que ocorre antes da região impede o efeito; se o efeito já foi linearizado/iniciado, a operação passa a potencialmente executada e PC02 contém os recursos. Não afirmar atomicidade entre SQLite, rede, thread e processo.

Antes de qualquer byte/spawn capaz de causar efeito, uma recusa comprovada pode produzir `EffectNotSent` e `record_not_sent`. Depois do primeiro efeito possível ou quando a prova se perde, manter `OUTCOME_UNKNOWN`/`possible_effect=True`, sem replay automático. A guarda não deve interromper um frame no meio e classificar isso como not-sent. Ações internas de contenção pertencem à sessão própria; pedidos externos de interrupt/close continuam exigindo escopo e ownership válidos, mesmo quando podem operar após deadline.

Não adicionar novas enums/estágios ao NXL só para representar a implementação. Mapear para receipts atuais quando suficiente. `retry_safe` significa que não há risco de repetir efeito naquela recusa, não licença para alterar silenciosamente contexto/hash/ID nem para reenviar uma operação já registrada com outro significado.

#### Tarefas executáveis


##### PC03.01 — Mapear todos os efeitos

Listar spawn, submit, steer, interrupt, close, approval e input. Identificar onde cada um toca o provider e onde usa thread. Classificar controles de redução de risco versus ações que permitem trabalho.

**Aceite:** Tabela efeito → método → guarda → marca durável cobre cada caminho produtivo.


##### PC03.02 — Introduzir guarda tipada e estado corrente

Definir contexto de pré-efeito e acesso ao fence corrente sem depender de SQLite síncrono no loop. Garantir sincronização entre thread/loop, fechamento e renovação. Manter autoridade recebida do host.

**Aceite:** Não é possível usar apenas cópia vencida do contexto para validar write futuro.


##### PC03.03 — Revalidar após persistência

Inserir checagens depois dos awaits de admissão e marcação. Recusa anterior ao efeito atualiza journal de forma consistente; falha ao registrar a recusa preserva estado conservador.

**Aceite:** Regressão original de clock.advance durante mark_possible_effect passa.


##### PC03.04 — Levar a guarda ao write/spawn

Passar token/guarda à execução nativa por mecanismo interno, incluindo comandos adiados e to_thread. Auditar handshake, start/resume e replies. Não executar side effects irreversíveis ao apenas construir configuração.

**Aceite:** Fila nativa atrasada além do deadline não escreve nem cria processo novo.


##### PC03.05 — Resolver corrida com revoke/renew

Definir ponto de linearização curto e comportamento depois de possível efeito. Não segurar mutex de revogação durante write travado. Invalidar workers antigos por generation/fence, com callbacks tardios ignorados ou registrados sem ressuscitar estado.

**Aceite:** Revogação não pode ficar indefinidamente atrás do write; in-flight é contido, não falsamente desfeito.


##### PC03.06 — Preservar recibos e replay

Testar mesmo ID/hash após recusa, após marca durável, após write e após resultado desconhecido. Não transformar SESSION_CONFLICT existente em reuso sem decisão de contrato e migração.

**Aceite:** Nenhum retry duplica efeito ou reabre sessão automaticamente.


##### PC03.07 — Estender fault matrix

Criar pontos de injeção antes/depois de admit, marker, enqueue thread, pré-write, byte/spawn, resposta e commit final. Registrar traces com relógio/generation sem payload sensível.

**Aceite:** Cada janela tem estado esperado e teste; cancelamento não equivale a prova de rollback nativo.


**Cenários mínimos desta fase:** RC-03-01, RC-03-02, RC-03-03, RC-03-04, RC-03-05, RC-03-06, RC-03-07, RC-03-08, RC-03-09, RC-03-10.

**Gate de saída:** Atrasos em qualquer await/fila não permitem efeito sob contexto stale; crash/cancelamento preservam idempotência e incerteza reais.


### PC04 — Tratar fim de stream, cancelamento do observador e falta de observabilidade

**Prioridade:** P1 · **Dependências:** PC01, PC02 · **Achados:** F03.

**Objetivo.** Impedir novas execuções quando o Core perdeu o fluxo necessário para observar respostas, sem confundir EOF com término de turno ou morte do processo.

**Âncoras no código:** `src/nexus_connector_core/runtime.py:1191–1247,523–553`; `src/nexus_connector_core/event_reducer.py`; `tests/test_native_event_fairness.py`; `tests/test_event_ingest.py`.

**Rastreabilidade R3:** K04, K05, K06, K07, TK-18, TK-21, TK-26, TK-27.

#### Decisões e especificação

Distinguir término esperado de um stream encerrado pelo lifecycle do Core, EOF inesperado de iterador de sessão e exceção/cancelamento inesperado da tarefa observadora. Um terminal de turno seguido de ausência de novos tokens não é EOF do stream da sessão: não matar sessões multi-turn saudáveis.

Ao perder observação, marcar a sessão como indisponível para novo trabalho antes de aguardar persistência. Registrar um evento canônico de perda por stream epoch, notificar watchers e aplicar política de contenção de PC02. Se o banco falhar, manter fence local e diagnóstico, sem silêncio e sem confirmar evento durável.

`inspect`, `reconcile` e ações de contenção continuam disponíveis. Não responder aprovações pendentes sob correlação perdida só porque a solicitação existia antes. A política default deve recusar ampliação de efeitos nesse estado; negar/interromper pode ser viável se a versão do adaptador comprovar correlação, mas nunca inferir do EOF.

Evento de falha só é emitido uma vez por incidente/epoch; ACK/replay do mesmo evento não cria incidentes novos. Um stream posterior só é aceito com um caminho de reanexação/reconciliação explicitamente suportado. Não reiniciar pump, processo ou turno automaticamente para esconder EOF.

Se a implementação escolhe contenção imediata após perda da observação, isso deve ser uma política única, com drain limitado e ownership preservado; não introduzir uma segunda máquina de shutdown paralela.

#### Tarefas executáveis


##### PC04.01 — Classificar conclusões do pump

Adicionar tratamento explícito para esgotamento normal do iterador e para cancelamento. Identificar fechamento solicitado com token/generation de lifecycle, não por flags frágeis de instante.

**Aceite:** EOF com processo vivo não deixa a sessão gravável.


##### PC04.02 — Aplicar fence antes do evento

Fechar admissão e classificar observação perdida antes de await ao journal/sink. Garantir que próximos submit/steer sejam recusados com CoreError consistente.

**Aceite:** Mesmo com journal lento, a sessão não aceita novo trabalho invisível.


##### PC04.03 — Persistir e notificar incidente uma vez

Reusar categoria/error code coerentes com contrato, associar stream epoch e preservar sequência. Documentar como falha de armazenamento é reportada.

**Aceite:** Sem flood de eventos repetidos nem marcação fictícia de turn completed.


##### PC04.04 — Integrar com contenção

Usar coordenador PC02 e assegurar inspect/reconcile/stop em estado degradado. Não excluir ownership ou slots na perda do canal.

**Aceite:** Sessão inacessível ainda pode ser contida; resultado real preservado.


##### PC04.05 — Revisar pending requests e events

Invalidar capacidade de responder requests stale, preservar registro histórico e liberar cache só quando seguro. Não descartar terminais que estavam duravelmente enfileirados antes do EOF.

**Aceite:** HITL não aprova o turno errado; terminal real é reapresentável mesmo com falha posterior.


##### PC04.06 — Qualificar semântica por adaptador

Testar Codex, Pi e Claude com peers multi-turn: terminal de turno versus EOF global. Documentar reconexão/reattach realmente suportados.

**Aceite:** Fim normal de um turno não mata runtime; perda global nunca é mascarada como idle saudável.


**Cenários mínimos desta fase:** RC-04-01, RC-04-02, RC-04-03, RC-04-04, RC-04-05, RC-04-06, RC-04-07, RC-04-08.

**Gate de saída:** EOF inesperado bloqueia trabalho e fica observável; EOF esperado não gera erro falso; process/turn/handoff continuam semanticamente distintos.


### PC05 — Uniformizar IDs, erros e leitura de histórico legado

**Prioridade:** P1 · **Dependências:** PC00 · **Achados:** F05.

**Objetivo.** Toda operação nova admitida deve ser consultável pelo mesmo contrato; IDs antigos não podem se tornar irrecuperáveis com a correção.

**Âncoras no código:** `src/nexus_connector_core/runtime.py:721–739,1304–1308`; `src/nexus_connector_core/models.py`; `src/nexus_connector_core/protocol.py`; `contracts/generate.py`; `tests/test_reconcile_validation.py`; `tests/test_protocol.py`.

**Rastreabilidade R3:** K01, K02, K10.3, TK-05, TK-06, TK-07, TK-37.

#### Decisões e especificação

Fixar para novos IDs externos Nexus o limite normativo já presente no bundle: string não vazia com até 160 caracteres. Não converter números, remover espaços, truncar, normalizar Unicode, aplicar lower-case nem gerar hash substituto silencioso. A igualdade do identificador é exata. Preservar restrições existentes de prefixos internos e documentá-las; não estender a regra Nexus a IDs nativos de provider que têm contratos próprios.

Definir fonte única de limites consumida pela validação Python e pela geração dos schemas. Testar semântica de comprimento Unicode entre linguagem/wire; rejeitar Unicode inválido e manter teto de bytes do frame independente do limite de caracteres. Limites de batches continuam 256 IDs distintos quando assim especificados; testar um item inválido no fim para garantir ausência de efeitos parciais.

IDs acima de 160 já persistidos no dev0 exigem compatibilidade de leitura, não aceitação irrestrita de novas escritas. Implementar consulta local pública, somente leitura, por chave exata e namespace, para evidência legada de até o limite antigo observado (256). Essa porta não é um novo endpoint NXL; não duplica/admite/reexecuta operações. O host pode usar um ID de requisição válido para obter/exportar um registro diagnóstico cujo legacy_id é dado opaco. Caso a integração remota precise representar esses registros no wire, a mudança precisa de envelope diagnóstico versionado acordado com os dois hosts, nunca violar silenciosamente o campo operation_id atual.

Replays antigos não devem virar novas execuções por causa da validação mais estrita. O caminho ordinário pode recusar um ID inválido, mas deve oferecer orientação de consulta legada e não remapear para ID curto. Sessões/IDs internos afetados recebem o mesmo inventário. Preservar hashes e registros originais; dados não são apagados nem reidentificados.

Erros de entrada de operações devem ser CoreError tipados antes de persistência mutável, não ValueError perdido na recuperação. Erros de configuração local do construtor podem manter sua classe documentada; não converter indiscriminadamente bugs internos em erro recuperável.

#### Tarefas executáveis


##### PC05.01 — Centralizar política de identificadores

Criar constante/validador comum para Nexus IDs e usar na geração do bundle. Inventariar validações externas, session keys, eventos, namespace, paginação e prefixos internos.

**Aceite:** API e schema têm exatamente o mesmo domínio aceito para cada campo.


##### PC05.02 — Validar na fronteira pública

Aplicar validação antes de journal/efeitos em open/submit/control/approval/reconcile/queries. Distinguir native_id de operation_id; preservar formas válidas de request IDs do provider.

**Aceite:** Invalidez é tipada e não causa admissão parcial ou coerção silenciosa.


##### PC05.03 — Testar equivalência Python/wire

Gerar casos positivos/negativos de fronteira, Unicode e tipos. Comparar validação dos dataclasses/ports com bundle gerado.

**Aceite:** Não há divergência de 160/161 nem de tipos bool/int/string.


##### PC05.04 — Inventariar registros legados

Adicionar diagnóstico read-only que conte/localize IDs persistidos incompatíveis por namespace. Não varrer/exportar outros agentes em resposta a uma credencial de escopo limitado.

**Aceite:** Inventário produz plano de compatibilidade, sem escrever/rekey ou alterar intent_hash.


##### PC05.05 — Oferecer consulta legada pública e limitada

Implementar leitura exata de histórico 161–256 caracteres, com rate/batch/namespace bounded, sem abrir exceção na admissão nova. Documentar handoff para Server/Connector quando necessário.

**Aceite:** Registro pré-fix é recuperável; invocar leitura nunca dá spawn/write ou muda outcome.


##### PC05.06 — Atualizar bundle e documentação juntos

Regenerar schemas/fixtures/manifest e identificar se houve mudança de representação ou só fix da implementação. Se novo campo público mudar o wire, bump explícito e negociação, não editar arquivo gerado manualmente.

**Aceite:** Hashes/revisão consistentes e consumidores usam o mesmo artefato.


##### PC05.07 — Cobrir migração e rollback

Abrir cópia de journal dev0 com long IDs, testar backup/consulta/reopen e downgrade somente quando schema permitir. Não resetar banco/slots em caso de incompatibilidade.

**Aceite:** Dados e recibos históricos preservados; rollback operacional tem limites declarados.


**Cenários mínimos desta fase:** RC-05-01, RC-05-02, RC-05-03, RC-05-04, RC-05-05, RC-05-06, RC-05-07, RC-05-08, RC-05-09.

**Gate de saída:** IDs novos válidos são admitidos e reconciliáveis; inválidos são recusados antes de efeito; histórico dev0 continua consultável sem reexecução.


### PC06 — Publicar composição real e contrato suportado dos consumidores

**Prioridade:** P1 · **Dependências:** PC02, PC03, PC04, PC05 · **Achados:** G01.

**Objetivo.** Permitir Server e Connector instanciar o runtime real pelo mesmo contrato público, sem imports privados ou conhecimento dos protocolos dos providers.

**Âncoras no código:** `src/nexus_connector_core/__init__.py`; `src/nexus_connector_core/ports.py:19–53`; `src/nexus_connector_core/runtime.py:150–162`; `src/nexus_connector_core/native/runtime_bridge.py:301–325`; `docs/api.md`; `README.md`; `tools/consumer_smoke.py`.

**Rastreabilidade R3:** K01, K03, K10.5, K11.2, TK-04, TK-10, TK-41.

#### Decisões e especificação

Publicar factory/construtor suportado para o runtime real. Nome ilustrativo: `create_runtime(...)` ou builder equivalente; não presumir que já existe. A entrada recebe journal/ledger, resolução tipada de environment/secret refs, roots e candidates aprovados, callbacks limitados de approval/resume/ação Pi, relógio, budgets e capacidades. Esconder `CopiedAdapterFactory` e parsers nativos. Não apenas reexportar classe privada com dezenas de detalhes de provider como contrato definitivo.

A aplicação continua resolvendo credenciais locais, autorizando agente/binding e hospedando transportes/daemon. Core não faz login, HTTP para buscar chave, WSS, MCP nem busca global de identidades. Configuração HTTP do harness é dado declarativo apontando diretamente para o Server.

Definir propriedade/lifecycle de cada recurso: journal injetado pelo host não é fechado arbitrariamente pelo Core; journal criado por conveniência é fechado pelo owner declarado. `shutdown()` encerra sessões; `aclose()`/context manager encerra recursos próprios segundo contrato; não eliminar capacidade de ler histórico apenas por terminar runtimes. Expor também metadados públicos de API/NXL/manifest e relatório de capacidades/preflight.

Harmonizar `RuntimeCore` e exports, incluindo `persisted_lease`; revisar NativeSession/NativeFactory se callbacks de força/guarda novos forem necessários. `OperationKernel` e `LocalRuntimeCore` devem depender dos ports que de fato consomem, não de herança concreta SQLite. Implementar adapter de journal host-owned nos testes sem `_db`/`_connection` do Core.

Provar composição com wheel instalado fora da árvore-fonte. Fakes apenas demonstram uso do contrato. Um peer subprocesso contido exercita factory real e lifecycle, mas continua sem qualificar provider. Handoff para consumidores deve diferenciar esses níveis e pin exato do wheel/hash. Construção não abre provider nem cria subprocesso por si só.

#### Tarefas executáveis


##### PC06.01 — Definir e implementar factory pública

Projetar uma entrada pequena e tipada para composição produtiva, delegando internamente aos adapters existentes. Documentar todos os campos e rejeitar combinações inválidas antes de resolver secrets/spawn.

**Aceite:** Server/Connector não importam native.runtime_bridge ou classes Copied* para funcionar.


##### PC06.02 — Alinhar ports e exports

Adicionar métodos faltantes, especialmente persisted_lease, e comparar runtime/Protocol/docs/export set. Formalizar force/observe/guard e lifecycle de journal.

**Aceite:** Teste de conformidade de assinatura e type checking dos consumidores passa.


##### PC06.03 — Desacoplar tipos concretos de journal

Trocar dependências de implementação por Protocols completos. Cobrir queries, CAS, process births, storage e slot ledger de fato usados. Não esconder dependências via getattr não documentado.

**Aceite:** Journal host-owned passa o mesmo kit sem subclassing de SQLiteJournal.


##### PC06.04 — Formalizar ownership e cleanup

Documentar quem abre/fecha journal, worker, ledger, sessões, sink e callbacks. Tratar exception durante construção/start sem destruir recursos injetados de outro host.

**Aceite:** Dois Cores com stores isolados não encerram recursos um do outro.


##### PC06.05 — Reescrever exemplos e smokes públicos

Atualizar README/docs/examples e criar dois programas mínimos em pastas fora do pacote. Usar factory real com peer controlado e caminho fake só para contratos.

**Aceite:** Código de exemplo é executado em teste e não usa imports proibidos.


##### PC06.06 — Gerar handoff consumível

Emitir documento com versão, wheel SHA, API/NXL, callbacks obrigatórios, defaults/bounds, erros, snippets de lifecycle e migrações. Acessar outros repos só se disponíveis e autorizado; do contrário entregar contrato.

**Aceite:** Consumidores conseguem integrar sem inventar factory, IDs ou adapters.


##### PC06.07 — Estabelecer política de evolução

Versionar alterações públicas e bundle, registrar incompatibilidades de journal/lifecycle. Usar preview development honestamente até gates; não congelar API sobre testes só fake.

**Aceite:** Release notes distinguem correção, breaking change, migração e capacidades ainda não qualificadas.


**Cenários mínimos desta fase:** RC-06-01, RC-06-02, RC-06-03, RC-06-04, RC-06-05, RC-06-06, RC-06-07, RC-06-08, RC-06-09.

**Gate de saída:** Dois consumidores mínimos independentes usam somente API pública; composição real e journal alternativo funcionam; não há dependência de classes privadas nos hosts.


### PC07 — Liberar objetos de sessões encerradas sem perder histórico ou ownership

**Prioridade:** P2 · **Dependências:** PC04, PC06 · **Achados:** F06.

**Objetivo.** Impedir crescimento ilimitado de referências a adapters, tasks e buffers depois de encerramento comprovado.

**Âncoras no código:** `src/nexus_connector_core/runtime.py:111–138,959–979`; `src/nexus_connector_core/journal.py`; `tests/test_runtime.py`; `tests/test_native_event_fairness.py`.

**Rastreabilidade R3:** K04.2, K04.5, K10.4, TK-18, TK-20, TK-40.

#### Decisões e especificação

Separar o registro vivo da sessão, um snapshot leve de histórico recente e o journal durável. O limite de sessões ativas não é um limite implícito de histórico; estabelecer limites próprios de quantidade e bytes para snapshots e filas/caches, com defaults documentados.

Evict somente depois de comprovar que os recursos próprios terminaram e que tarefas associadas não precisam mais do objeto nativo. Desassociar pump, watcher, sink, shutdown/force tasks e caches de approvals de forma race-safe. Completion callbacks não podem reinstalar entradas antigas ou ressuscitar estado. Não fazer a task aguardar a si mesma nem cancelar a única tarefa que ainda garante contenção.

Receipts, claims e tombstones de idempotência continuam no journal conforme política de retenção. O sink de notificação não deve manter adapter pesado vivo indefinidamente; retomar a partir de cursor durável ou spool bounded separado. Evict de memória não significa ACK, compactação nem perda de evento não confirmado.

Sessões unknown retêm ownership mínimo necessário. Se o conjunto de incertezas esgota capacidade, bloquear novas admissões e diagnosticar; não liberar slots nem matar por PID apenas para estabilizar memória. Testar memória por weakrefs/contagem e série de lotes, não apenas RSS, que pode variar com allocator.

#### Tarefas executáveis


##### PC07.01 — Separar estruturas vivas e snapshots

Criar registry vivo e cache bounded de snapshots leves, ou design equivalente. Não expor dicts mutáveis ao host. Definir quando inspect consulta memória versus journal.

**Aceite:** Histórico não mantém NativeSession nem closure de tasks que o referenciam.


##### PC07.02 — Implementar teardown seguro

Desligar/join tarefas concluídas, soltar buffers/caches/closures após parada observada. Proteger contra callbacks tardios e await de si mesmo.

**Aceite:** Weakrefs de objetos encerrados tornam-se coletáveis; nenhum watcher infinito de sessão fechada.


##### PC07.03 — Manter replay e idempotência

Preservar receipts, claims, eventos pendentes e tombstones necessários. Definir query para sessão evictada sem inventar estado atual de processo a partir do histórico.

**Aceite:** Reconcile continua funcionando depois de evicção e restart.


##### PC07.04 — Desacoplar notificações lentas

Fazer sink operar sobre cursor/snapshot leve e limites próprios. Falha do consumidor não prende adapter físico indefinidamente.

**Aceite:** Consumidor lento não causa memória ilimitada nem descarte silencioso de eventos.


##### PC07.05 — Preservar sessões incertas

Reduzir somente dados não necessários, mantendo ownership/handles para contenção real e reserva de capacidade. Diagnosticar pressão em vez de expurgar unknown.

**Aceite:** Não houve falso stopped nem nova admissão quando slots permanecem reservados.


##### PC07.06 — Executar soak e regressões

Rodar lotes de start/stop com fakes e peers reais, intercalando falhas e consumidores lentos. Medir native handles vivos, tasks, bytes e latências.

**Aceite:** Crescimento de objetos encerrados estabiliza dentro dos limites definidos; evidência não depende só de uma coleta de lixo pontual.


**Cenários mínimos desta fase:** RC-07-01, RC-07-02, RC-07-03, RC-07-04, RC-07-05, RC-07-06, RC-07-07.

**Gate de saída:** Muitos ciclos terminados não retêm adapters pesados; consultas históricas permanecem corretas; sessões incertas não são apagadas.


### PC08 — Aplicar o modelo solicitado e tornar configuração efetiva verificável

**Prioridade:** P2 · **Dependências:** PC06 · **Achados:** F07.

**Objetivo.** Não aceitar uma escolha de modelo que desaparece antes de chegar ao runtime; preservar defaults explícitos e limitações reais de cada adaptador.

**Âncoras no código:** `src/nexus_connector_core/profiles.py:17–58`; `src/nexus_connector_core/native/runtime_bridge.py:325–408`; `src/nexus_connector_core/native/adapters/codex.py`; `tests/test_profiles.py`; `tests/test_native_runtime_bridge.py`.

**Rastreabilidade R3:** K03.2, K05, K06, K07, TK-12, TK-13, TK-21, TK-27, TK-36.

#### Decisões e especificação

Mapear `LaunchIntent.model` para o mecanismo nativo que a versão qualificada efetivamente suporta. Codex pode configurar thread/start, override ou mecanismo equivalente conforme contrato verificado; Claude pode exigir argv/start específico. Não adivinhar parâmetros por analogia com outro provider, nem adicionar flags sem confrontar a implementação/documentação da versão testada.

Definir precedência: intenção explícita do perfil aprovado prevalece sobre default permitido; conflitos com configuração já aprovada ou resume precisam ser resolvidos de forma explícita, nunca silenciosamente. Model ausente mantém default documentado. Modelo inválido pelo provider não pode gerar sucesso de aplicação; diferenciar falha pré-efeito comprovada de rejeição depois de processo/turno ter sido iniciado.

O fingerprint deve representar a configuração que será aplicada, não somente um desejo descartado. Expor solicitado/aplicado e, quando o provider informar, modelo efetivo observado. Não preencher `effective_model` por cópia do solicitado sem confirmação; usar desconhecido ou não reportado.

Não instalar modelos, trocar provedor ou rodar sondas com custo por causa de prepare/discover sem aprovação. Uma opção de modelo não suportada deve ser recusada; não degradar para default para aparentar compatibilidade.

#### Tarefas executáveis


##### PC08.01 — Mapear suporte real por adaptador

Inspecionar contratos da versão de teste e adapter existente, guardar referência/versionamento na evidência. Definir onde modelo entra e quando pode mudar.

**Aceite:** Tabela Codex/Pi/Claude informa mecanismo, precedência e limitações qualificadas.


##### PC08.02 — Corrigir preparo e factory

Encaminhar campo tipado para a representação nativa apropriada sem shell concatenado. Aplicar mesma decisão em start/resume/submits quando o protocolo exigir.

**Aceite:** Spies originais deixam de perder o marcador de modelo.


##### PC08.03 — Tornar configuração efetiva rastreável

Calcular fingerprint da representação normalizada realmente aplicada, incluindo decisão de default quando conhecida. Separar requested/applied/observed sem inventar confirmação.

**Aceite:** Mudança de modelo altera perfil correto; ausência mantém compatibilidade documentada.


##### PC08.04 — Tratar erro e incompatibilidade

Rejeitar preferência incompatível antes de efeito quando possível; se provider só rejeita após handshake, refletir estágio real e cleanup. Não fazer fallback de modelo silencioso.

**Aceite:** Erro tipado e diagnóstico acionável, sem mascarar custo ou identidade do runtime.


##### PC08.05 — Cobrir resume e mudança de perfil

Testar resume autorizado com modelo igual, conflito ou desconhecido. Não reutilizar sessão com perfil diferente para evitar relançamento; pedir novo vínculo/execução conforme política existente.

**Aceite:** Mudança não altera trabalho em curso sem aprovação nem finge mesmo profile hash.


##### PC08.06 — Qualificar do teste ao provider

Adicionar testes de factory, frames/argv e uma campanha real aprovada por adaptador-alvo. Redigir prompts e credenciais; registrar modelo observado quando exposto.

**Aceite:** Passing de spy não é reportado como qualificação de provider real.


**Cenários mínimos desta fase:** RC-08-01, RC-08-02, RC-08-03, RC-08-04, RC-08-05, RC-08-06, RC-08-07, RC-08-08.

**Gate de saída:** Codex e Claude recebem a seleção nos pontos nativos corretos; Pi não regride; o estado relatado distingue intenção de confirmação.


### PC09 — Separar qualificação portável de binding físico local

**Prioridade:** P2 · **Dependências:** PC05, PC06 · **Achados:** G02.

**Objetivo.** Uma instalação equivalente deve conservar a qualificação de build sem perder a detecção de mudança de caminho, binário ou configuração local.

**Âncoras no código:** `src/nexus_connector_core/native/adapters/compatibility.py:21–54`; `src/nexus_connector_core/discovery.py:62–107`; `src/nexus_connector_core/native/runtime_bridge.py:325–334`; `docs/compatibility.md`.

**Rastreabilidade R3:** K02.2, K03, K10, TK-09, TK-11, TK-13, TK-36.

#### Decisões e especificação

Criar dois identificadores com finalidade explícita. `build_identity` é uma proposta de nome para conteúdo e protocolo qualificados: adapter, versão/protocolo, plataforma/arquitetura, artefatos executáveis e dependências relevantes. `binding_fingerprint` permanece local: caminhos reais, arquivo/identidade do SO, root/config/env refs e build selecionado. Não substituir um pelo outro.

Para Pi, o hash portável precisa considerar Node e o código/dependências carregadas do Pi, não apenas o pequeno `cli.js` se ele carrega outros módulos. Version string e `package.json` sozinhos não provam conteúdo. Definir manifest de artefatos a partir do formato instalado, com inventário determinístico e sem segredos. Não incluir path absoluto do usuário no build portável. Extensões/plugins não fazem parte de qualificação implícita: entram no perfil aprovado e reduzem capacidades conforme escopo demonstrado.

Qualificação associa build/protocolo e capacidades testadas a evidência de versão/plataforma. Registro no catálogo não é aprovação da instalação nem autorização de execução. Três estados ficam distintos: candidato encontrado; binding local aprovado; build/capability qualificado. Capacidade efetiva é a interseção de adapter, build, plataforma/containment, perfil e autorização do host.

Migrar a lista embutida existente sem reinterpretar hashes antigos como portáveis. Registros sem evidência suficiente ficam históricos/não promovidos até qualificação equivalente. Não desabilitar a checagem nem usar intervalos amplos de versão para fazer hosts novos funcionarem.

Definir cache e invalidação de hashing de artefatos. Otimizações por mtime/inode não podem transformar detecção de drift em aceitação cega quando ameaça inclui modificação do conteúdo. Revalidar prepare→open e diagnosticar mudança antes de efeito.

#### Tarefas executáveis


##### PC09.01 — Definir as duas identidades

Publicar campos, algoritmo/hash versionado, normalização e escopo. Inventariar todos os usos do fingerprint atual para separar qualificação, drift, resume e cache.

**Aceite:** Nenhum uso troca portabilidade por perda de verificação local.


##### PC09.02 — Implementar manifest portável de build

Derivar conteúdo completo relevante por layout suportado, incluindo Node+Pi e dependências relevantes. Produzir digest determinístico sem path absoluto ou dados pessoais.

**Aceite:** Duas instalações equivalentes geram a mesma build_identity; mudança material altera digest.


##### PC09.03 — Manter binding local e TOCTOU

Preservar caminho/identidade de arquivo/root/config no fingerprint local e revalidações antes de open. Mover instalação exige novo bind aprovado, não autenticação de usuário Nexus.

**Aceite:** Movimento muda binding; alteração entre prepare/open bloqueia efeito.


##### PC09.04 — Atualizar catálogo de qualificação

Armazenar capacidades/evidência por build/platform/arch. Converter registros existentes só com prova de equivalência; retirar contradições da documentação atual sem apagar história.

**Aceite:** Versão não qualificada é diagnosticada claramente, não silenciosamente habilitada.


##### PC09.05 — Expor estados e caps ao host

Retornar descoberta, aprovação local, qualificação e motivo de restrição como dados públicos. O host decide UX; Core não cria wizard, login ou fallback inseguro.

**Aceite:** Server/Connector não precisam interpretar listas privadas de hashes para orientar usuário.


##### PC09.06 — Testar cache, drift e provenance

Cobrir cache stale, mudança de dependência e plugin, binário trocado e arquivos idênticos em caminhos distintos. Guardar evidence hashes e rastreabilidade de manifesto.

**Aceite:** Manifest e capacidade observada auditáveis e sem referências a home/token.


**Cenários mínimos desta fase:** RC-09-01, RC-09-02, RC-09-03, RC-09-04, RC-09-05, RC-09-06, RC-09-07, RC-09-08.

**Gate de saída:** Mesmo build aprovado em caminhos diferentes conserva qualificação; mover/trocar instalação continua invalidando o binding anterior.


### PC10 — Concluir discovery dos layouts suportados sem executar wrappers arbitrários

**Prioridade:** P2 · **Dependências:** PC09 · **Achados:** G03.

**Objetivo.** Resolver instalações comuns de Codex, Claude e Pi em candidatos confiáveis sem exigir que o usuário encontre manualmente binários internos.

**Âncoras no código:** `src/nexus_connector_core/discovery.py:75–95,110–134,183–213`; `src/nexus_connector_core/profiles.py`; `tests/test_discovery_probe.py`; `tests/test_native_registry.py`.

**Rastreabilidade R3:** K03.1, K03.2, K03.3, TK-11, TK-12, TK-13, TK-14.

#### Decisões e especificação

Criar resolvers por layouts explicitamente suportados. Descoberta passiva lê metadados/arquivos em raízes confiáveis; probe ativo é outra etapa, limitada, contida e autorizada. Não executar `.cmd`, `.bat`, shell script ou wrapper arbitrário para descobrir o que faz. Interpretar apenas formatos conhecidos estritamente; desconhecido exige seleção explícita ou diagnóstico.

Em Pi, construir par Node+entrypoint automaticamente nos layouts testados e validar as duas partes. Em Windows, resolver shims conhecidos para o executável/script final com paths de espaços/Unicode. Não rodar shell com concatenação nem aceitar o primeiro homônimo no cwd/PATH. Symlinks e writable paths são verificados conforme política do host.

Quando há múltiplas instalações, retornar opções ordenadas e justificadas; uma seleção já aprovada pode ser reutilizada somente sem drift. Não misturar discovery de binários com discovery de credenciais ou lista global de agentes. A identidade chega explicitamente pelo host.

Retornar códigos e ações prescritivas para wrapper desconhecido, versão não qualificada, probe indisponível, root faltante e autenticação do provider ausente. Não propor bypass de permissões ou copiar todo home/env como solução.

#### Tarefas executáveis


##### PC10.01 — Inventariar layouts-alvo

Registrar formatos de instalação por provider/plataforma usados na campanha, sem presumir que todos os package managers são iguais. Separar resolver de probe.

**Aceite:** Matriz concreta de layouts testados e não suportados.


##### PC10.02 — Implementar resolução Pi Node+CLI

Resolver metadados conhecidos para Node e entrypoint, validar conteúdo/paths e devolver candidato composto. Aplicar build/binding de PC09.

**Aceite:** Instalação Pi comum testada não exige selecionar dois arquivos internos manualmente.


##### PC10.03 — Resolver wrappers conhecidos com segurança

Fazer parsing estrito de shims conhecidos ou manifest do instalador; recusar scripts arbitrários. Usar argv estruturado e raízes confiáveis.

**Aceite:** Sem execução de shell durante discovery passivo nem expansão de comandos do wrapper.


##### PC10.04 — Gerenciar ambiguidade e drift

Devolver candidatos distintos com origem, confiança, qualificação e motivo. Reusar escolha aprovada só se fingerprints coincidem; atualizar binding via host quando necessário.

**Aceite:** Escolha não muda silenciosamente por ordem do PATH ou novo pacote.


##### PC10.05 — Conter probes e diagnosticar

Executar somente probes necessários sob backend PC11/preflight, timeout, cap de stdout/stderr e bytes. Cache sem executar código no import.

**Aceite:** Probe travado não deixa processo sem controle nem devolve inventário de sucesso falso.


##### PC10.06 — Testar experiência de instalação normal

Escrever fixtures realistas de paths/layouts e executar campanha por SO alvo. Orientação da API pede decisões de intenção, não JSON de perfil ou argumentos internos.

**Aceite:** Handoff para CLI Server/Connector mostra escolha simples de harness/projeto mantendo segurança.


**Cenários mínimos desta fase:** RC-10-01, RC-10-02, RC-10-03, RC-10-04, RC-10-05, RC-10-06, RC-10-07, RC-10-08.

**Gate de saída:** Instalações comuns testadas são detectadas e preparadas sem localizar manualmente cli.js; layouts não suportados falham com orientação segura.


### PC11 — Preflight e qualificação real dos backends de contenção

**Prioridade:** P1 · **Dependências:** PC02, PC06 · **Achados:** G05.

**Objetivo.** Recusar trabalho produtivo em ambiente sem mecanismo de contenção exigido e demonstrar as garantias nos SOs realmente suportados.

**Âncoras no código:** `src/nexus_connector_core/native/process/linux_process_guardian.py:44–45,61–85,131–147`; `src/nexus_connector_core/native/process`; `tests/test_owned_process.py`; `tests/test_process_birth_crash.py`; `tests/test_tree_census.py`.

**Rastreabilidade R3:** K04, K10.2, TK-17, TK-19, TK-20, TK-38.

#### Decisões e especificação

O preflight deve verificar requisitos reais do backend escolhido antes de spawn de provider e antes de probes que possam criar árvore incontrolável. Plataforma nominal não é prova: conferir interfaces de `/proc` requeridas, pidfd/subreaper quando utilizados, jobs/guards, permissões e limitações do container/session do SO. Não exigir um recurso que o backend selecionado não usa; não fazer fallback ad hoc para `kill(pid)`.

Distinguir inspeção passiva de capacidade e autoteste ativo seguro. Se for necessário criar processo sentinela, usar peer inofensivo com contenção bootstrap validada, prazos e limpeza; não criar um processo potencialmente órfão para testar se é possível contê-lo. Limitação retorna erro tipado antes de resolver segredos ou iniciar harness produtivo.

O ambiente da auditoria não tinha o arquivo `children` utilizado pelo guardian. Não modificar a suíte para ignorar a falta nem tratar como sucesso de Linux. Introduzir diagnóstico específico e executar campanha real em host Linux compatível. Executar equivalentes Windows/macOS apenas onde houver backend previsto/qualificado; plataformas pendentes continuam explícitas.

Não liberar slots incertos para compensar falhas ambientais. Expor diagnóstico administrativo read-only da reserva e origem, sem oferecer comando de purge automático. Uma observação de processo não concede ownership depois de restart. Matar owner/daemon durante teste exige sandbox e autorização local, nunca processo de trabalho do usuário.

#### Tarefas executáveis


##### PC11.01 — Mapear requisitos por backend

Listar APIs/arquivos/permissões efetivamente necessários por SO e seus limites. Definir relatório de capabilities/diagnóstico público para PC06.

**Aceite:** Nenhuma suposição baseada só em sys.platform decide readiness.


##### PC11.02 — Implementar preflight passivo

Verificar requisitos sem spawn de provider, secret read ou alteração de serviço. Cache de sucesso deve invalidar quando contexto/permissões relevantes mudarem.

**Aceite:** Falta de children/guard necessário é detectada antes de slot produtivo ou lançamento.


##### PC11.03 — Adicionar autoteste seguro opcional

Quando necessário, exercitar backend com peer curto e conteúdo inofensivo, com autorização e cleanup garantido pela base suportada. Separar do discovery passivo.

**Aceite:** Nenhum autoteste cria árvore órfã para depois concluir que não havia contenção.


##### PC11.04 — Retornar erro e remediação tipados

Propor código como PROCESS_CONTAINMENT_UNAVAILABLE, stage=preflight, retry_safe=true/possible_effect=false somente antes de spawn. Incluir motivo redigido e requisito faltante.

**Aceite:** Usuário recebe causa real, não apenas slots esgotados; códigos finais entram no catálogo público.


##### PC11.05 — Qualificar Linux e cenários restritos

Executar com peer filho/neto, setsid quando pertinente, owner crash e proc restrito. Não presumir que um guardian real foi aprovado porque unit tests passam.

**Aceite:** Campanha contém kernel/container/recursos observados, comandos e comprovação do resultado.


##### PC11.06 — Qualificar demais plataformas-alvo

Validar jobs/guards e lifecycle de user session/logout onde contrato promete suporte. Registrar versão/arquitetura e limitar claims às combinações testadas.

**Aceite:** Windows/macOS não recebem PASS por analogia com Linux nem por evidência antiga sem replay.


##### PC11.07 — Preservar observação e slots

Testar PID reutilizado, birth evidence, processo externo e falha de confirmação. Restaurar histórico sem assumir posse de PID persistido.

**Aceite:** Slots só liberados por prova legítima; backend indisponível não dispara reset do journal.


**Cenários mínimos desta fase:** RC-11-01, RC-11-02, RC-11-03, RC-11-04, RC-11-05, RC-11-06, RC-11-07, RC-11-08, RC-11-09.

**Gate de saída:** Ambiente incompatível falha cedo e de forma prescritiva; onde suporte é anunciado, árvore própria e falha do owner são qualificadas.


### PC12 — Integrar attach pela API pública e preservar processos externos

**Prioridade:** P2 · **Dependências:** PC06, PC09, PC11 · **Achados:** G04.

**Objetivo.** Completar o modo attach previsto sem ligá-lo por flag fictícia e sem transformar alvo externo em processo pertencente ao Core.

**Âncoras no código:** `src/nexus_connector_core/profiles.py:22–24`; `src/nexus_connector_core/native/runtime_bridge.py:327–329`; `src/nexus_connector_core/native/adapters/compatibility.py`; `src/nexus_connector_core/native/adapters/claude_code_attach.py`; `tests/test_attach_extracted.py`.

**Rastreabilidade R3:** K08, TK-30, TK-31, TK-32, TK-38.

#### Decisões e especificação

Attach é uma intenção e um lifecycle distintos de managed. A porta pública recebe alvo escolhido/aprovado com identidade técnica verificável: processo/nascimento, sessão/canal, versão/substrato, workspace/binding e escopo de controle. Não anexar ao primeiro processo encontrado nem inferir consentimento por pertencer ao mesmo usuário do SO.

Preservar o adapter legado como implementação, mas integrar prepare/open ou porta equivalente tipada, inspect, eventos e detach. `stop`/shutdown/lease expiry em attach significam desanexar controle e revogar handles, não terminar árvore externa. Interrupt nativo só é permitido com correlação e autorização próprias; nunca enviar comandos para outra conversa porque o PID coincide.

A ausência de documentação estável do substrato exige qualificação explícita por versão/SO. Se não existir um caminho demonstrável no ambiente disponível, a tarefa permanece BLOCKED/NOT_RUN e a capability continua falsa. Isso não deve impedir um wheel development dos modos gerenciados, mas impede declarar todo o escopo R3 concluído.

Attach não promete adotar qualquer conversa já aberta nem restaurar autorização depois de restart. Reconexão/retomada precisam revalidar alvo e permissão. Nenhum caminho MCP stdio, wrapper de terminal genérico ou OCR de tela deve ser introduzido para aparentar suporte.

#### Tarefas executáveis


##### PC12.01 — Inventariar o adapter legado

Mapear substrato, suposições, testes existentes, operações suportadas e dependências de SO. Não confundir testes extraídos com sessão externa real.

**Aceite:** Proveniência e capacidades demonstradas preservadas; lacunas rastreadas.


##### PC12.02 — Definir intenção e alvo públicos

Adicionar tipos/protocolos mínimos de attach, target evidence e política de detach, com autorização fornecida pelo host. Evitar módulo/classe arbitrária vinda da rede.

**Aceite:** Host escolhe alvo sem conhecer implementação interna; input hostil é recusado.


##### PC12.03 — Integrar execução sem ownership

Permitir composição pública do adapter attach e eventos; marcar recurso externo em todas as rotas de controle/encerramento.

**Aceite:** Nenhuma reserva/árvore gerenciada concede direito de kill ao alvo externo.


##### PC12.04 — Revalidar alvo e correlação

Checar troca do processo/sessão entre descoberta/attach e em reanexação. Invalidar handles em lease/revoke/EOF.

**Aceite:** PID/sessão reciclados não recebem comandos antigos.


##### PC12.05 — Implementar detach e falhas

Usar PC02 para fechamento local da capacidade e cleanup, não força do processo externo. Manter estado honesto de perda de observação e operações incertas.

**Aceite:** Stop/shutdown/revoke não encerram a aplicação do usuário.


##### PC12.06 — Qualificar sem habilitar flags artificiais

Executar fixtures e campanha real do substrato, registrar versão/SO/capabilities; suportes ausentes retornam CAPABILITY_UNSUPPORTED.

**Aceite:** ATTACH_QUALIFIED só muda com evidência; pendência não some do release report.


**Cenários mínimos desta fase:** RC-12-01, RC-12-02, RC-12-03, RC-12-04, RC-12-05, RC-12-06, RC-12-07.

**Gate de saída:** Attach/detach operam pelo contrato público em combinação qualificada; alvos externos nunca recebem kill implícito; limitações continuam explícitas.


### PC13 — Qualificar modos gerenciados, MCP HTTP direto e integração dos dois hosts

**Prioridade:** P1 · **Dependências:** PC07, PC08, PC09, PC10, PC11 · **Achados:** G06.

**Objetivo.** Demonstrar que o mesmo Core funciona local e remotamente e que as capacidades declaradas correspondem a execuções reais, sem reintroduzir MCP no Connector/Core.

**Âncoras no código:** `plans/implementation/status.md`; `plans/implementation/matrix.md`; `docs/compatibility.md`; `tools/consumer_smoke.py`; `src/nexus_connector_core/harness_config.py`; `src/nexus_connector_core/pi_extension`; `tests/test_native_action_bridge.py`.

**Rastreabilidade R3:** K05, K06, K07, K09, K10, K11.2, TK-21, TK-23, TK-26, TK-27, TK-29, TK-33, TK-34, TK-35, TK-36, J01, J16, J17, J18, J32, J33, J34.

#### Decisões e especificação

Executar camadas separadas: API pública/fakes; peers de processo contidos; provider real por build; Server+Core local; Server↔canal já acordado↔Connector+Core remoto em hosts distintos. Um peer simulado não substitui provider; processo remoto no mesmo host não substitui prova distribuída.

Começar por um adaptador (Codex, salvo impedimento técnico documentado) nos dois caminhos com o mesmo wheel/hash. O Server remoto de teste não deve precisar do binário, credencial do provider nem checkout remoto. Usar scopes de agente existentes; nenhum login/cadastro de usuário Nexus. O transporte entre hosts continua o contrato acordado (WSS/NXL nos planos R3), implementado pelos aplicativos, não pelo Core. Este plano não redefine WSS para SSE nem acrescenta proxy.

MCP, quando suportado pelo harness, é direto para o HTTP(S) do Nexus Server. O Core só gera configuração cliente e secret refs; não implementa cliente/proxy/servidor SDK MCP. Verificar origem/destino do tráfego e isolamento: um harness externo tools-only já iniciado continua consumindo MCP sem daemon Connector. Não testar isso parando um Connector que possui aquele processo gerenciado e esperar que o processo sobreviva, pois shutdown deve contê-lo.

Pi sem MCP usa extensão nativa tipada limitada e backend fornecido pelo host. Testar claim/context/complete reais conforme domínio do Server; término do turno não é conclusão automática de handoff. Não parsear texto do modelo, não aceitar envelopes MCP e não transmitir chave administrativa de múltiplos agentes.

Integrar fault tests sem alterar outros repositórios silenciosamente. O agente do Core fornece wheel, conformance, cenários e handoffs; agentes dos hosts implementam suas superfícies e entregam evidência. Dependência externa fica BLOCKED, não é resolvida copiando app para dentro do Core. Uma rodada posterior fecha os providers/combinações declarados no escopo; capability não demonstrada continua false.

#### Tarefas executáveis


##### PC13.01 — Executar campanha determinística integrada

Rodar regressões F/G, suite original pertinente e conformance com wheel. Confirmar que correções simultâneas não reintroduzem lock/unknown/EOF/ID divergente.

**Aceite:** Logs e XML agregados por camada; nenhum novo FAIL não explicado no escopo liberado.


##### PC13.02 — Qualificar um provider vertical

Executar start, multi-turn, streaming, terminal, input/approval aplicável, interrupt, stop e recovery do primeiro provider em host suportado.

**Aceite:** Versão/build/artefatos e semânticas efetivas registradas, incluindo recursos não suportados.


##### PC13.03 — Coordenar integração local e remota

Entregar contrato PC06 ao Server/Connector, pinando wheel e manifesto idênticos. Executar local sem Connector e remoto sem dependências do harness no Server.

**Aceite:** Evidência inclui topologia, SHAs dos três repos, hashes instalados e resultado por cenário.


##### PC13.04 — Provar MCP HTTP direto

Gerar configuração real por sessão/perfil e inspecionar conexão ao Server. Testar tools-only sem Connector com harness independente. Auditar ausência de MCP SDK/server/proxy/stdio em Core/Connector.

**Aceite:** Nenhuma chamada MCP depende de relay Connector; stdio nativo dos adapters continua intacto.


##### PC13.05 — Qualificar demais modos gerenciados e extensão Pi

Rodar Claude e Pi com mesma disciplina de evidência, incluindo settled/steer conforme versão e extensão nativa estruturada. Não acrescentar funcionalidades de provider não qualificadas.

**Aceite:** Multi-turn/controles/execute_work só anunciados onde efetivamente comprovados.


##### PC13.06 — Exercitar falhas cruzadas

Queda de canal, restart Server, restart Connector, lease expiry, journal cheio, stdout flood, consumidor lento e resultado incerto. Manter exclusividade de consumo/handoff no Server.

**Aceite:** Sem duplicação de turno após reconectar, sem ack prematuro, sem takeover de processo desconhecido.


##### PC13.07 — Consolidar matriz sem inflar evidência

Atualizar TK/J e RC separadamente, ligando casos a comandos/ambientes. Preservar evidências antigas como históricas. Casos attach de PC12 não podem virar PASS por managed.

**Aceite:** Gate declara exatamente provedores, layouts, SOs e limites aceitos; restante PENDING/BLOCKED.


**Cenários mínimos desta fase:** RC-13-01, RC-13-02, RC-13-03, RC-13-04, RC-13-05, RC-13-06, RC-13-07, RC-13-08, RC-13-09, RC-13-10, RC-13-11, RC-13-12.

**Gate de saída:** Um caminho local e um remoto em hosts distintos usam o mesmo adapter/wheel; providers/capacidades declarados têm evidência; itens não executados permanecem pendentes.


### PC14 — Fechar migrações, documentação, artefatos e gates de liberação

**Prioridade:** P1 · **Dependências:** PC06, PC07, PC08, PC09, PC10, PC11, PC13 · **Achados:** G01, G06.

**Objetivo.** Entregar um Core corrigido com limitações explícitas, consumidores pinados, migração segura e evidência suficiente para cada nível de uso.

**Âncoras no código:** `pyproject.toml`; `contracts/generate.py`; `docs/api.md`; `docs/lifecycle.md`; `docs/compatibility.md`; `tools/build_artifacts.py`; `tools/validate_release.py`; `tools/verify_offline_artifacts.py`.

**Rastreabilidade R3:** K11.1, K11.2, K11.3, K11.4, K11.5, TK-41, TK-42, TK-43, TK-44, TK-45.

#### Decisões e especificação

Empacotar wheel/sdist locais imutáveis, com versão development nova não colidente, schemas/manifest/fixtures, extensão Pi, py.typed e licenças. Não publicar PyPI, criar release remoto ou atualizar pin dos consumidores sem autorização do responsável. O plano autoriza alterações locais no Core e produção de artefatos, não efeitos externos de publicação.

Atualizar documentação para corresponder à implementação corrigida: lifecycle assíncrono, guarda de efeito, contenção independente, semântica de unknown, journal/cancelamento, nova factory, IDs e consulta legada, qualificação portável, modelos e discovery. Remover contradições de estado atual sem apagar evidência histórica. Não usar `development-partial` como razão para ignorar regressões de segurança; o rótulo delimita escopo demonstrado.

Estruturar liberação incremental: E0 contratos/fakes disponíveis; E1 Core corrigido em plataforma/provider delimitados; E2 integração local+remota demonstrada; E3 escopo R3 completo, incluindo attach e capacidades/plataformas que foram explicitamente prometidas. E0/E1 não dependem de PC12 nem de todos os hosts estarem prontos. Este fechamento PC14 documenta E2 quando disponível; entrega integral E3 exige também PC12 e pendências reais encerradas.

Migrações de schema são transacionais/versionadas, com backup sobre cópia e teste dev0→novo. Nunca mudar algoritmo de intent_hash de registros antigos sem compatibilidade versionada. Rollback binário só quando seguro com schema/semântica atuais; preferir drain, backup e forward fix se downgrade perder informação. Não instruir apagar journal/state dir/slots.

Relatório final deve distinguir código implementado, testes executados, qualificação, bloqueios externos e próxima ação. A contagem de testes não substitui aceite. O arquivo de status não pode afirmar API estável, quatro modos completos ou suporte universal se seus gates não foram satisfeitos.

#### Tarefas executáveis


##### PC14.01 — Consolidar regressões e cobertura

Mapear todas as F/G, tarefas PC e cenários RC a testes/commits, além de TK/J. Documentar testes portados e diferenças de contrato. Não reduzir expectativa para passar.

**Aceite:** Todas as falhas críticas têm regressão positiva; casos não executados permanecem visíveis.


##### PC14.02 — Ensaiar migração e recuperação

Testar cópia de journal dev0 com IDs longos, markers incertos, claims, leases, slots e eventos sem ACK. Criar backup consistente e validar reopen/downgrade permitido.

**Aceite:** Nenhuma perda/rekey/limpeza de ownership; plano de rollback é executável e honesto.


##### PC14.03 — Gerar e verificar wheel/sdist

Usar tools de build/validação existentes após inspecionar interfaces, comparar builds limpos e instalar fora do repo. Incluir manifest e digest final.

**Aceite:** Import/conformance/resources/type markers funcionando sem árvore-fonte/rede no runtime.


##### PC14.04 — Atualizar documentação e exemplos

Substituir imports privados, explicar requested/applied/observed model, unknown, journal async, preflight e caps. Registrar release notes e migrações de API.

**Aceite:** Exemplos executados; nenhum texto atual contradiz a matriz.


##### PC14.05 — Entregar handoffs aos dois agentes

Fornecer contrato de consumo, wheel/hash/revisões, breaking changes e cenários de integração. Emitir pendências por owner; não editar os outros repos inadvertidamente.

**Aceite:** Ambos agentes sabem integrar sem duplicar schemas/runtime/journal semântico.


##### PC14.06 — Aplicar gates de liberação

Checar E0/E1/E2/E3 separadamente e bloquear claims acima da evidência. Attach não bloqueia preview gerenciado, mas continua requisito aberto de E3.

**Aceite:** Arquivo release_decision registra fatos, limites e ações sem promover parcial a completo.


##### PC14.07 — Encerrar com evidências e riscos

Gerar resumo de mudanças, comandos/exit codes, artifacts SHA, backlog residual e confirmação de ausência de publicação remota. Incluir problemas descobertos durante execução fora da auditoria.

**Aceite:** Responsável recebe entrega auditável; nenhum FAIL oculto por contagem total verde.


**Cenários mínimos desta fase:** RC-14-01, RC-14-02, RC-14-03, RC-14-04, RC-14-05, RC-14-06, RC-14-07, RC-14-08.

**Gate de saída:** Artefato reproduzível/instalável e documentação coerente; nível de liberação explícito; migração e bloqueios rastreados; nenhuma publicação automática.


## 7. Plano de commits e controle de alterações

Usar commits pequenos por invariantes, com testes juntos. Sugestões de assunto: `fix(journal): move SQLite ownership off event loop`; `fix(runtime): contain expired sessions without send lock`; `fix(kernel): fence effects after durable waits`; `fix(events): fence unexpected session EOF`; `fix(contract): unify identifiers and preserve legacy reads`; `feat(api): expose supported runtime composition`. São sugestões, não nomes de branches/commits existentes.

Não fazer um commit gigante que mistura troca de schema, API, leases, qualificação e UI. Manter uma transição executável entre commits quando possível. Se o tipo/lifecycle do journal mudar, migrar fixtures/exemplos no mesmo conjunto e documentar para consumidores. Não manter duas implementações produtivas divergentes indefinidamente em nome de compatibilidade.

Refatoração é permitida quando necessária para invariantes, mas preservar proveniência de adapters e casos legados. Não adicionar abstrações sem uso concreto pelos dois hosts. Não trocar biblioteca de banco, empacotamento ou framework async só para evitar corrigir o port existente.

## 8. Comandos de validação e cuidados

Executar em clone de trabalho e diretórios de teste, nunca sobre journal, credenciais ou projetos de produção. Os comandos abaixo usam interfaces encontradas no snapshot; antes de executar scripts que tenham mudado, conferir `--help` ou seu código. Dependências precisam estar disponíveis; ausência de rede/dependências é BLOCKED, não autorização para stub de canonicalização.

```bash
# Referência real e contexto; não altera a árvore.
git rev-parse HEAD
git status --short
python --version

# Em ambiente virtual já selecionado; registrar versões resolvidas.
python -m pip install -e '.[test]'
python -m pip freeze

# Baseline completo: executar também a campanha de processos em host suportado.
python -m pytest -q --junitxml=evidence/pytest-current.xml

# Sementes históricas deste pacote; ajustar o path do pacote/clone.
python /CAMINHO/PLANO_CORRECAO_NEXUS_CONNECTOR_CORE/regressoes_originais/run_regressions.py   --repo /CAMINHO/CLONE_CORE --junitxml=/CAMINHO/evidence/audit-seeds.xml

# Build local existente no snapshot.
python tools/build_artifacts.py --outdir dist
python tools/validate_release.py --version <VERSAO_REAL_DO_PACOTE> --allow-development

# No ambiente que instalou o wheel fora da árvore-fonte.
python -m nexus_connector_core.conformance   --manifest-sha256 sha256:<HASH_REAL_DO_MANIFESTO> --allow-development-partial
```

Os scripts `tools/verify_wheel.py`, `tools/verify_offline_artifacts.py` e `tools/consumer_smoke.py` devem ser preservados/evoluídos, não substituídos por import da árvore `src`. No snapshot, consumer_smoke exige modo isolado e argumentos de role/manifest/wheel; o remote atual é teste de contrato, não uma implementação do Connector. Adicionar o caminho de composição real pública e documentar o comando final no handoff.

Os nove testes históricos podem exigir port de fixtures/lifecycle após a correção. O runner original tem timeout de 90 segundos e imports de `tests/test_runtime.py`; não o apresentar como ferramenta universal da API nova. O agente deverá integrar equivalentes estáveis à suíte do repositório.

## 9. O que constitui conclusão

**Tarefa concluída:** código e documentação do escopo presentes, regressão pertinente executada, resultado/evidência registrados, nenhuma redução de invariante, review das fronteiras afetadas. "Implementado, não testado" não é DONE com aceite, mas pode ser registrado em nota de progresso.

**Correção de achado concluída:** todas as suas tarefas/gates satisfeitos; comportamento original não reaparece no HEAD final; novas corridas e compatibilidade verificadas. Testar apenas o caminho feliz não fecha F01–F05.

**Liberação incremental:** ver `04_GATES_E_EVIDENCIAS.md`. Uma dependência externa pode bloquear o teste conjunto sem bloquear o wheel de desenvolvimento; não bloqueia a honestidade do relatório. Entregar o que foi comprovado, com backlog residual e owner, sem pedir a cada fase autorização já dada para implementar o Core.

**Escopo completo R3:** exige também capacidades originalmente planejadas e ainda abertas — em particular attach real, providers/builds declarados, testes de plataforma pertinentes e integração dos dois hosts. Declarar pendência com precisão é obrigatório; não transformar incapacidade de executar localmente em comprovação automática de suporte.

## 10. Proibições de atalhos

Não remover journal para baixar latência. Não executar SQLite no loop atrás de função `async`. Não fazer queues ilimitadas. Não marcar stopped porque a task foi cancelada. Não liberar slots incertos. Não esperar o lock de send para conter o próprio send. Não trocar errors por sucesso. Não truncar/rekey IDs. Não ignorar modelo solicitado. Não qualificar build só por nome/versão. Não executar wrapper desconhecido durante discovery. Não ligar attach por flag sem teste. Não duplicar adapters/contratos nos hosts. Não introduzir MCP stdio, servidor ou proxy no Core/Connector. Não publicar pacote/release por consequência de build local.

**A entrega deve corrigir a base existente e permitir integração segura, não criar uma implementação paralela nem apenas reescrever documentação.**
