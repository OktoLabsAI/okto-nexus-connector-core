# Reavaliação independente — nexus-connector-core após C1

**Snapshot:** `e6b630543a6f8b2723347d2f8cf605be86b200d6`  
**Pacote:** `nexus-connector-core 0.2.0.dev0`  
**Data da análise:** 27/09/2026  
**Referências:** plano R3 HTTP-only, plano de correção C1, auditoria do snapshot `706b16a90c54a654551519cdc357bd6fedb9427e`.

## 1. Parecer executivo

Houve evolução concreta: journal e ledger receberam worker dedicado; há factory pública, IDs uniformes com leitura legada, mapeamento de modelo, tratamento de EOF, cleanup e uma distinção inicial entre build portátil e binding local. Não recomendo reescrita.

**Entretanto, a entrega C1 ainda não está concluída e eu não ratifico E1 para este snapshot.** Os problemas não se resumem a attach, billing, PyPI ou disponibilidade dos repositórios consumidores. Há falhas reproduzíveis inteiramente dentro do Core, inclusive no caminho de autorização e contenção física. O nível apropriado continua sendo preview/integração experimental (E0), com versão fixada, sem substituição operacional dos runtimes nos consumidores.

Foram escritos **14 testes independentes, todos reproduzindo falhas, agrupadas em dez achados**. A evidência de cada um está neste pacote. Os testes descrevem o comportamento exigido; portanto, falhar é o resultado observado da versão auditada, não um teste a ser normalizado para aceitar o defeito. Nenhum deles usa provider real ou depende do guardian Linux.

A arquitetura permanece correta: identidade centrada no agente; autoridade/inbox/handoff fora do Core; Server e Connector consumindo a mesma biblioteca; MCP HTTP direto entre harness e Nexus Server; nenhum MCP stdio/proxy/fachada reintroduzido. Stdio nativo de runtime continua permitido.

## 2. Escopo, método e resultados

O ZIP fornecido é a fonte de verdade. O comentário do arquivo identifica o commit acima. Comparei seus bytes com o ZIP anterior e confrontei implementação/testes/matriz com C1. Consultei alguns arquivos do mesmo commit pelo conector GitHub para atribuição precisa; não avaliei HEAD posterior nem os aplicativos Server/Connector.

### 2.1. Mudanças de código

Comparação entre os dois ZIPs: **29 arquivos modificados, 52 adicionados e nenhum removido**. Após os testes, conferi os **332 arquivos originais** do novo ZIP: nenhum foi alterado. Build foi feito em uma segunda cópia; caches e testes da auditoria não são alterações de produção.

### 2.2. Execuções feitas nesta auditoria

| Verificação | Resultado observado |
|---|---|
| Suíte completa do repositório | 633 PASS, 119 FAIL, 19 SKIP; 771 casos |
| Subconjunto C1/regressões/worker | 70 PASS, 3 FAIL, 2 SKIP; 75 casos, já incluídos na suíte completa |
| Testes independentes desta reavaliação | 14 FAIL; dez grupos de problemas; sem providers/processos reais |
| Wheel e sdist | Build concluído via setuptools.build_meta |
| Instalação do wheel fora da árvore-fonte | Passou, com import de create_runtime |
| Bundle NXL instalado | Passou com opt-in development-partial: nove arquivos, 49 frames, 17 modelos, três vetores |

Os tempos registrados nos JUnit são aproximadamente 49,41 s (completa), 5,52 s (C1) e 7,32 s (independentes); são medições locais, não indicadores de desempenho do produto. A matriz RC é uma matriz de cenários/requisitos, não a mesma unidade de contagem que pytest.

### 2.3. Limitação Linux e as 119 falhas

Neste sandbox, `/proc/self/task/<pid>/children` não está disponível ao guardian. A suíte completa produziu 86 falhas por capacidade de processos retida, 24 por parada de árvore de probe não confirmada, seis recusas de preflight, uma incompatibilidade da mensagem esperada depois da recusa, uma falha de observação de encerramento após morte do owner e uma falha do próprio teste de preflight. Isso totaliza 119, mas **não representa 119 bugs independentes**.

A classificação acima é por assinatura observada. Não prova que cada teste passaria em outro Linux; tampouco autoriza afirmar que o produto passou na suíte completa neste ambiente. No subconjunto C1, duas falhas decorreram da recusa de preflight em testes de Codex/modelo e uma da ausência de proc_children. Um warning adicional revela coroutine close não aguardada no teste RC-03-03.

Os logs Windows/WSL2 e os resultados 697/74 e 753/18 presentes no repositório são **evidências declaradas pelo agente executor**, não campanhas reproduzidas nesta auditoria. Não executei providers reais, billing, Windows, macOS, logout, nem integração em dois hosts.

### 2.4. Ambiente e dependências

Python 3.13.5 em venv de auditoria; pytest 9.0.2, jsonschema 4.26.0, setuptools 82.0.1. A rede de pip não estava disponível. Usei o código oficial exato de rfc8785 0.1.4 obtido pelo conector GitHub, conferindo os Git blob hashes dos dois módulos; não substituí a canonicalização por mock. O wheel foi instalado com --no-deps usando essas dependências já disponíveis. Os hashes do wheel recompilado são próprios desta execução e não equivalem aos artefatos normalizados citados pelo agente.

O manifesto NXL permanece development-partial. Passar sua verificação demonstra integridade/fixtures do bundle instalado; não prova E2, completude normativa nem interoperabilidade real.

## 3. Situação dos achados anteriores

| Achado anterior | Situação após inspeção e testes |
|---|---|
| F01 — lease × send travado | Parcial: novo coordenador existe; R01/R02 ainda impedem independência efetiva |
| F02 — deadline antes do efeito | Parcial: janela do journal corrigida; despacho tardio e spawn ainda falham em R03 |
| F03 — EOF admite trabalho | Caso simples tratado; EOF pode esperar o lock global em R01 e há regressão de replay R04 |
| F04 — SQLite no event loop | Operações correntes movidas para worker; nova fila ilimitada R05 e abertura síncrona merecem correção |
| F05 — IDs não reconciliáveis | Contrato 1–160 e leitura exata legada 161–256 implementados; não reproduzi a falha original |
| F06 — retenção de sessões | Caso simples melhorou; sink travado ainda retém adaptador depois da evicção, R10 |
| F07 — modelo ignorado | Mapeamento foi implementado para Codex/Claude; confirmação com providers reais permanece fora desta auditoria |
| G01 — API privada | create_runtime é avanço; resume e assinatura de environment continuam inconsistentes, R09 |
| G02 — build/binding | Separação inicial existe; raiz/cobertura do digest Pi ainda incorretas, R06 |
| G03 — descoberta | Helpers existem, mas não estão integrados ao caminho público, R08 |
| G04 — attach | Tipos e recusa explícita, sem modo real qualificado; pendência reconhecida e aceitável fora do escopo E1 |
| G05 — plataforma | Preflight produtivo existe; ABI e cobertura de probes incorretas, R07 |
| G06 — evidência | Melhor rastreabilidade, porém PASS e E1 excedem o que alguns testes demonstram |

Não fecho F01/F02/F03/F06 só porque suas sementes estreitas estão verdes: C1 exigiu cenários de falha mais amplos. Por outro lado, não reabro F05 sem evidência de defeito: os IDs e o caminho legado constituem uma correção aproveitável.

## 4. Achados confirmados

Prioridades são de execução do projeto, não CVSS: P1 bloqueia utilização operacional do caminho afetado; P2 deve ser resolvido para a capacidade ou operação sustentada correspondente.

### R01 — Journal sob lock global ainda bloqueia contenção e fechamento do fence por EOF

**Prioridade:** P1 · **C1:** PC01, PC02, PC04

**Código:** `runtime.py:567–607`; `runtime.py:1271–1303`; `runtime.py:1490–1516`; `runtime.py:1598–1628`. Caminhos relativos a `src/nexus_connector_core/`.

A nova checagem de admissão em memória e o coordenador de contenção são melhorias reais. Entretanto, `_send` adquire `self._lock` e aguarda `_existing`, que consulta o journal. O watcher da lease e o caminho de EOF também precisam desse lock global antes de prosseguir. Portanto, remover o lock do envio nativo não eliminou a dependência do armazenamento no caminho de segurança.

Envolvi o SQLiteJournal real em uma porta que retém `get_receipt` para uma operação específica. Com o submit esperando dentro do lock global, avancei o relógio injetado além da lease e da tolerância: a chamada física `force_stop` não ocorreu dentro da janela de observação. Liberar o journal permite ao fluxo continuar. Em outro teste, encerrei o stream enquanto a mesma leitura estava retida: o binding permaneceu sem `faulted` até o lock ficar disponível.

A primeira reprodução não mede a rapidez de um provider; ela demonstra uma dependência lógica. A segunda comprova que a afirmação “fence antes de qualquer I/O” não se sustenta quando outra coroutine já segura o lock durante I/O.

**Impacto:** Um armazenamento travado pode neutralizar a contenção por lease e atrasar o bloqueio da sessão após perder observabilidade. Atinge Server e Connector por compartilharem o Core.

**Correção requerida:** Não manter o lock de estado/segurança durante await de journal, callbacks ou comandos nativos. Separar snapshot/mutação atômica de memória, I/O e reconciliação com revalidação de geração. O latch de contenção precisa poder fechar independentemente das operações duráveis. Não mover o mesmo deadlock para outro lock.

**Aceite:** Com get_receipt, admit, record_event e release de slot retidos separadamente, o fence fecha e a contenção física é solicitada no orçamento previsto. Persistência e recibos são reconciliados depois, sem inventar parada nem liberar slot incerto.

**Regressões:**

- `test_r01_storage_read_under_global_lock_must_not_block_lease_containment`
- `test_r01b_eof_fence_must_not_wait_for_journal_read_lock`

### R02 — Força e observação usam o mesmo pool de threads dos envios e leituras normais

**Prioridade:** P1 · **C1:** PC02, PC11

**Código:** `native/runtime_bridge.py:189–196`; `native/runtime_bridge.py:205–242`; `native/runtime_bridge.py:340–347`; `runtime.py:1385–1432`. Caminhos relativos a `src/nexus_connector_core/`.

`CopiedAdapterSession.force_stop()` usa `asyncio.to_thread`, assim como envio normal, observação e leitura de eventos. Essas chamadas compartilham o executor padrão do loop. O método ganhou independência em relação ao mutex do adaptador, mas não em relação à capacidade de execução.

Configurei o loop de teste com um worker, ocupei-o com trabalho normal bloqueado e invoquei o método real `force_stop` da bridge sobre um peer síncrono simples. O loop continuou responsivo, mas a função de força não foi chamada enquanto o worker permaneceu ocupado. Após liberar o worker, a chamada aconteceu. Limitar a um worker torna determinístico o cenário de saturação; o mesmo princípio se aplica a um pool maior totalmente ocupado.

A coexistência de leituras de stream bloqueantes no mesmo pool amplia o risco. Esta é uma inferência estrutural a partir do código, não uma campanha com dezenas de providers reais.

**Impacto:** O mecanismo de emergência pode ficar na fila atrás da atividade que deveria interromper. A independência física pedida em PC02.04 ainda não está demonstrada.

**Correção requerida:** Separar capacidade reservada de controle/observação do pool usado por dados e streams. Dar orçamento explícito à solicitação e à observação de contenção, com recursos limitados e ownership claro. Não resolver criando threads ilimitadas nem prometendo que cancelamento de await encerra uma thread.

**Aceite:** Saturar totalmente os executores de envio e stream; ainda assim, a chamada física de força deve ser alcançada sem liberar os workers normais. Testar também shutdown e a ausência de confirmação de parada.

**Regressões:**

- `test_r02_force_must_have_capacity_independent_of_default_thread_pool`

### R03 — A guarda não consulta o prazo real na thread e não cobre o spawn após callbacks

**Prioridade:** P1 · **C1:** PC03

**Código:** `native/runtime_bridge.py:62–98`; `native/runtime_bridge.py:189–196`; `native/runtime_bridge.py:379–480`; `runtime.py:306–370`. Caminhos relativos a `src/nexus_connector_core/`.

O kernel agora revalida depois da admissão e do marcador durável. Isso corrige a janela original da persistência. A nova EffectFence, porém, consulta somente flags de sessão; ela não compara o relógio monotônico com o deadline na thread. A flag lease_expired depende de o watcher executar.

Na primeira reprodução, o envio foi admitido dentro do prazo e enfileirado atrás de uma thread ocupada. Avancei o relógio além do deadline e liberei o worker antes da próxima execução do watcher. A bridge real escreveu a operação `late`. Não foi necessário falsificar a flag para isso: ela estava legitimamente desatualizada.

Na segunda reprodução usei `create_runtime` com sua factory real, mas com um conector síncrono de teste — nenhum processo foi criado. O callback de resolução de ambiente avançou o relógio além do deadline. Mesmo assim, a factory chegou a `connector.start`. Preflight e qualificação foram substituídos somente nesse teste sem processo para isolar a autorização; a sequência real de callbacks e chamada da factory foi preservada.

A factory aguarda ambiente, resume grant e/ou integração Pi antes de `asyncio.to_thread(connector.start)`, sem nova verificação no ponto de spawn. A EffectFence da sessão só é instalada depois de a abertura retornar.

**Impacto:** Uma autorização válida ao admitir não garante autorização válida ao enviar ou iniciar. Este é um bloqueador operacional diretamente contrário a PC03, não uma exigência nova.

**Correção requerida:** Criar uma guarda tipada vinculada à operação/sessão, com relógio monotônico corrente, deadline, gerações/revisões pertinentes e latch de contenção. Consultá-la depois de callbacks/filas e na fronteira efetiva de write/spawn. Formalizar a linearização da corrida com revoke/renew; distinguir comprovadamente não enviado de efeito possível.

**Aceite:** Cobrir vencimento durante journal, reserva de slot, ambiente, resume callback, action callback, espera de worker e imediatamente antes de write/spawn. A guarda deve começar válida e tornar-se inválida durante a execução do teste, não nascer previamente fechada.

**Regressões:**

- `test_r03_late_dispatch_checks_clock_not_only_watcher_flags`
- `test_r03b_factory_must_revalidate_after_environment_resolution`

### R04 — Fence novo esconde recibos já persistidos em repetições idempotentes

**Prioridade:** P2 · **C1:** PC03, PC05

**Código:** `runtime.py:567–607`. Caminhos relativos a `src/nexus_connector_core/`.

O novo fence de `_send` roda antes da consulta `_existing`. Se o binding está faulted, closing ou ainda retido como closed, uma repetição legítima do mesmo ID/hash é rejeitada antes de recuperar seu recibo.

Submeti `known` com sucesso, provoquei EOF e repeti exatamente a mesma operação com o mesmo contexto ainda válido. Recebi `EVENT_STREAM_UNAVAILABLE`, não o recibo anterior. Houve apenas uma escrita nativa: não estou afirmando duplicação de efeito. O problema é a perda do comportamento idempotente da resposta. Após remoção do binding em outro estágio, a ordem do código pode permitir novamente o lookup, tornando a resposta dependente do momento do cleanup.

**Impacto:** Complica retries e recuperação dos consumidores e pode devolver um erro de não envio para uma operação que já ocorreu. A ausência de duplicação observada não elimina a quebra do contrato.

**Correção requerida:** Separar leitura autorizada de recibo/deduplicação da autorização para um efeito novo, validando identidade e hash. Não reabrir a execução só para responder ao retry nem reintroduzir I/O sob o lock de contenção ao reorganizar a ordem.

**Aceite:** Mesmos ID/hash retornam o recibo conhecido após EOF/closing/stop; hash divergente continua sendo conflito; nenhuma segunda escrita ocorre. A resposta não deve depender da evicção já ter acontecido.

**Regressões:**

- `test_r04_duplicate_known_submit_survives_stream_fault`

### R05 — Fila de notificações do worker cresce sem limite sob carga sustentada

**Prioridade:** P2 · **C1:** PC01

**Código:** `offloop.py:71–76`; `offloop.py:138–154`; `offloop.py:215–249`. Caminhos relativos a `src/nexus_connector_core/`.

As filas normal e urgente possuem limites, mas `_wake` é uma SimpleQueue ilimitada. Cada unidade aceita acrescenta uma notificação. `_next_item` só consome essas notificações depois de encontrar ambas as filas de trabalho vazias.

Mantive uma cadeia de 200 unidades, sempre adicionando a próxima antes de concluir a atual, com capacidade normal=1 e urgente=1. Ao parar a última unidade, havia zero unidades pendentes nas filas de trabalho e 199 notificações acumuladas. Enquanto a carga mantiver trabalho disponível, esse contador cresce com o total histórico de unidades, não com o limite de pendências.

São tags pequenas, não payloads completos. Ainda assim, a promessa de memória limitada é falsa e o fim da carga pode exigir consumir uma longa sequência de sinais obsoletos.

**Impacto:** Crescimento evitável de memória e custo de despertar em serviços de longa duração. É um defeito novo introduzido pela solução de journal off-loop.

**Correção requerida:** Usar notificação coalescida, Condition/Event ou contabilização limitada coerente com as filas, sem perder wakeups na corrida enqueue/sleep. Verificar também justiça entre filas e reservar recursos para controles; esses últimos pontos são revisão recomendada, não novos defeitos reproduzidos nesta contagem.

**Aceite:** Ensaio sustentado sem esvaziar filas por longos intervalos mantém notificações e memória proporcionais à capacidade configurada, não ao total processado. Testar wakeup concorrente e shutdown.

**Regressões:**

- `test_r05_wake_notifications_are_bounded_under_sustained_load`

### R06 — Identidade de build Pi usa raiz errada e omite dependências resolvíveis fora dela

**Prioridade:** P2 · **C1:** PC09

**Código:** `discovery.py:71–101`; `profiles.py:verificação de build Pi`; `build_identity.py:pi_build_identity`. Caminhos relativos a `src/nexus_connector_core/`.

O caminho reconhecido é `node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js`. Seu `parents[2]` é o pacote pi-coding-agent; `parents[3]`, usado como package_root, é o escopo @earendil-works. Assim, a árvore hashada não corresponde à unidade descrita no comentário.

Duas fixtures demonstram efeitos opostos: adicionar um pacote irmão sem relação com Pi dentro do mesmo escopo muda o hash; alterar uma dependência declarada no package.json e instalada diretamente em node_modules, fora do escopo, não muda o hash.

A segunda fixture comprova cobertura insuficiente para o layout de dependência montado. Não constitui afirmação de que um provider real específico carregou aquele módulo nesta auditoria. O critério correto precisa cobrir o código que a instalação qualificada pode executar, incluindo a resolução de dependências pertinente.

**Impacto:** Requalificações por arquivos irrelevantes e alterações relevantes não representadas na identidade de build. Isso prejudica portabilidade e confiança no gate de qualificação do Pi.

**Correção requerida:** Corrigir a raiz e definir o conjunto de artefatos carregáveis: entrypoint, manifesto, dependências transitivas ou bundle autocontido comprovado. Impor limites durante enumeração e leitura. Separar esse digest portátil do binding local. Rever aceitação por fingerprint legado para que ela não contorne a cobertura nova.

**Aceite:** Mesmo conteúdo em diretório diferente preserva a identidade; pacote irrelevante não a altera; modificar dependência executável a altera; alteração depois de prepare é detectada antes do efeito; qualificação não vira autorização de versões desconhecidas.

**Regressões:**

- `test_r06_pi_build_ignores_unrelated_sibling_package`
- `test_r06b_pi_build_covers_resolvable_dependencies_outside_scope`

### R07 — Preflight Linux consulta ABI incorreta e probes ativos não passam pelo gate

**Prioridade:** P1 · **C1:** PC10, PC11

**Código:** `native/process/preflight.py:83–116`; `discovery.py:160–187`; `native/process/__init__.py:spawn_owned_process`. Caminhos relativos a `src/nexus_connector_core/`.

O código comenta PR_GET_CHILD_SUBREAPER e chama `prctl(52, 0, 0, 0, 0)`. No cabeçalho Linux, PR_GET_CHILD_SUBREAPER é 37 e exige um ponteiro de saída para int; 52 é PR_GET_SPECULATION_CTRL. O teste independente interceptou exatamente `(52, 0, 0, 0, 0)`. Portanto, um status “subreaper: ok” desse código não comprova a capacidade pretendida.

Separadamente, `_probe_selected_version` aciona diretamente o observer de versão. A factory produtiva possui require_containment, mas esse probe não o utiliza antes de chegar ao caminho que inicia o processo de versão. Injetei uma recusa de contenção e um observer-sentinela sem processo: o observer foi alcançado, mostrando que o gate não foi consultado nesse caminho.

Há ainda um defeito de diagnóstico visível por inspeção: require_containment monta a string detail e depois a descarta ao lançar CoreError. O mapa detalhado existe na função passiva, mas não é transportado por essa exceção.

**Impacto:** Preflight pode testar outra funcionalidade e os probes podem criar trabalho antes de recusar um ambiente sem contenção. Não confundir isso com as limitações reais de /proc do sandbox da auditoria: são questões distintas.

**Correção requerida:** Usar ABI correta, ctypes com tipos e ponteiro apropriados, validação de retorno e erros. Passar probes ativos pelo mesmo gate de contenção antes do spawn. Preservar diagnóstico estruturado/redigido. Qualificar Win32 separadamente, sem inferir validade a partir de um teste Linux.

**Aceite:** Teste verifica número da operação e ponteiro, não apenas status textual. Negar cada requisito de backend impede qualquer observer/spawn ativo. Rodar campanha real no SO qualificado; ambiente limitado resulta em recusa antecipada e não em cascata de processos incertos.

**Regressões:**

- `test_r07_preflight_queries_actual_subreaper_abi`
- `test_r07b_active_version_probe_must_refuse_before_observer_if_containment_unavailable`

### R08 — Helpers novos de discovery não alimentam a descoberta pública do runtime

**Prioridade:** P2 · **C1:** PC10

**Código:** `runtime.py:233–239`; `discovery.py:discover_path`; `discovery.py:discover_pi_releases`; `discovery.py:resolve_windows_npm_shim`; `composition.py:create_runtime`. Caminhos relativos a `src/nexus_connector_core/`.

A implementação acrescentou descoberta de releases Pi e resolução declarativa de shims. Mas `LocalRuntimeCore.discover()` continua chamando apenas discover_path. O fluxo público não compõe a resolução de releases Pi que foi criada.

Montei um layout aceito pelo helper, incluindo raiz confiável e Node selecionado: discover_pi_releases encontrou o candidato; runtime.discover para pi_rpc devolveu inventário vazio. O teste passa raízes confiáveis ao construtor para não atribuir o resultado simplesmente a uma configuração ausente.

A factory pública create_runtime também não expõe o parâmetro trusted_discovery_roots do construtor. Isso requer um contrato claro de configuração/descoberta pública, não lógica de instalação duplicada nos dois aplicativos.

**Impacto:** O código auxiliar existe, mas Server e Connector ainda não obtêm a experiência prometida pela operação pública. O usuário ou cada host teria de conhecer detalhes da instalação.

**Correção requerida:** Compor os resolvedores suportados em um único serviço de discovery público, recebendo raízes/instalações aprovadas por um contrato explícito. Preservar a distinção entre encontrar, selecionar, aprovar e executar. Não executar wrappers arbitrários para ampliar cobertura.

**Aceite:** Os layouts declarados funcionam via a mesma API pública consumida pelos hosts, inclusive múltiplos candidatos e diagnóstico prescritivo. Nenhum consumidor importa helper privado ou reimplementa parsing de instalação.

**Regressões:**

- `test_r08_discovery_public_path_reuses_pi_layout_resolution`

### R09 — Composição pública ainda exige tipo privado para resume e tem anotação incompatível

**Prioridade:** P2 · **C1:** PC06

**Código:** `composition.py:25–40`; `native/runtime_bridge.py:26–44`; `native/runtime_bridge.py:417–436`; `__init__.py`; `ports.py`. Caminhos relativos a `src/nexus_connector_core/`.

create_runtime foi introduzida corretamente e o caminho básico de composição ficou melhor. Contudo, o callback público codex_resume precisa devolver exatamente uma instância de CodexResumeGrant, validada com `type(x) is CodexResumeGrant`. O tipo está definido no módulo privado native.runtime_bridge e não possui exportação pública correspondente.

O teste independente verifica essa ausência, e a inspeção do type-check da factory confirma que não basta um DTO estrutural equivalente do consumidor. A API básica pode ser usada sem import privado; esse caminho de retomada ainda não.

Além disso, create_runtime anota o callback environment como recebendo InstallationCandidate, enquanto sua implementação e documentação da bridge o chamam com PreparedLaunch. Isso é uma divergência concreta de tipagem pública, não apenas preferência de nomenclatura.

**Impacto:** Consumidores que usem resume precisam depender do detalhe interno que PC06 deveria esconder. Tipagem e implementação de environment podem induzir integração incorreta.

**Correção requerida:** Publicar os DTOs/callbacks necessários em módulo suportado, com exports e Protocols coerentes. Ajustar a assinatura de environment e declarar o que é estável. Não exportar indiscriminadamente toda a bridge para resolver um único tipo.

**Aceite:** Consumidores externos, instalados pelo wheel, exercitam composição básica e resume usando apenas imports públicos; type checking confirma que a assinatura corresponde aos objetos realmente recebidos.

**Regressões:**

- `test_r09_public_resume_contract_is_constructible_without_private_import`

### R10 — Evicção do dicionário não libera adaptador retido por sink de eventos travado

**Prioridade:** P2 · **C1:** PC07

**Código:** `runtime.py:1100–1144`; `runtime.py:1536–1570`. Caminhos relativos a `src/nexus_connector_core/`.

O novo cleanup resolve o acúmulo simples de sessões encerradas, mas o evictor apenas espera tarefas com shield/timeout e, quando o prazo vence, remove a entrada de `_sessions`. A tarefa do sink pode continuar ativa e mantém referência ao binding e ao objeto nativo.

No teste, o callback de eventos do host permanece aguardando um Event. Encerro o runtime, observo parada e espero a evicção. Removo também a referência do factory fake e a referência local, e executo GC. A sessão já não está no dicionário, mas o weakref para o objeto nativo continua vivo por causa do sink pendente. Libero o callback no cleanup do teste; não deixo tarefa indefinida na auditoria.

O comportamento comprovado é retenção de memória/objetos, não processo ainda vivo. Remover um registro de um dicionário não prova liberação de todos os recursos ligados à sessão.

**Impacto:** Hosts com callbacks lentos ou travados podem acumular objetos nativos e tarefas ao longo da vida do daemon, apesar de a contagem de sessões aparentar estar limitada.

**Correção requerida:** Separar entrega de notificações da propriedade dos objetos nativos; gerenciar e cancelar tarefas cooperativas de sink com orçamento e sem confirmar entrega fictícia. Preservar cursor/replay no journal. Rastrear tarefas de cleanup no shutdown e não descartar ownership incerto.

**Aceite:** Após parada comprovada e cleanup, um callback que não retorna não retém adaptadores pesados nem gera coleção ilimitada de tarefas. Perda de notificação continua recuperável por replay durável, sem avançar cursor de evento não entregue.

**Regressões:**

- `test_r10_stopped_session_native_is_released_even_when_host_sink_stalls`

## 5. A matriz verde não demonstra integralmente o cenário nomeado

O repositório declara 120 RC PASS, nove BLOCKED, 94 tarefas DONE e seis BLOCKED. Essas são declarações rastreáveis, mas precisam ser reabertas nos itens atingidos pelas reproduções acima. É possível que um teste tenha passado e, ainda assim, não exercite a condição exigida pelo cenário.

### 5.1. RC-03-03: a lease já nasce marcada como expirada

`tests/test_pc03_effect_guard.py:72–116` cria uma EffectFence cujo probe devolve expired=True desde o início. O teste não impõe um executor de um worker, apesar do comentário, e a função held_send definida no corpo nem é instalada. Assim, a recusa pode acontecer na checagem do loop antes de alcançar a thread. Isso testa um fence já fechado, não a corrida “operação válida enfileirada; thread começa depois do prazo”. Nesta auditoria, o cenário real de transição falhou em R03.

A mesma execução emitiu RuntimeWarning por coroutine `_SlowThreadNative.close` não aguardada. A fixture combina métodos assíncronos com uma bridge que espera conector síncrono; deve ser ajustada para corresponder à fronteira real.

### 5.2. Outros exemplos que precisam de evidência específica

| RC declarado PASS | Evidência descrita | O que ainda precisa ser demonstrado |
|---|---|---|
| RC-09-02, dependência alterada | Teste modifica CLI/conteúdo do pacote | Cobertura da dependência transitiva realmente resolvível, inclusive fora do escopo; R06 falhou |
| RC-09-04, drift após prepare | Alteração entre seleção e prepare | Alteração depois de prepare e antes do efeito; não é a mesma janela |
| RC-11-07, probe sem backend | Status do preflight passivo | Observer/spawn ativo não é alcançado após recusa; R07 falhou |
| RC-13-07, extensão Pi autorizada | Campanha sintética com backend canônico fake | Integração real com domínio/host, em camada separada de PASS sintético |
| RC-14-02, falha no meio de migração | Reaberturas sucessivas estáveis | Fault injection em ponto de migração/transação e integridade após retomada; se não há migração de schema, registrar explicitamente o requisito aplicável |

Isso não invalida os testes úteis nem constitui uma conclusão sobre intenção do agente. Significa que a classificação da evidência precisa ser mais precisa. Não substituir um PASS abrangente por outro teste também estreito: vincular invariantes, fault points e observações concretas.

## 6. Pontos de revisão adicionais, não contados nos dez achados reproduzidos

**Abertura assíncrona do journal.** SQLiteJournal.__init__ chama OffLoopExecutor.start, que espera `_started.wait()` de forma síncrona. Se a construção ocorrer em um loop ativo, o chamador ainda espera o setup do banco de forma bloqueante. C1 PC01.06 pedia abertura e encerramento assíncronos; há aclose, mas falta uma entrada de criação assíncrona ou uma restrição clara e enforced para construir fora do loop. Não executei fault injection adicional nessa abertura; é constatação do encadeamento síncrono.

**Preflight Windows.** A declaração de ctypes para handles e a validação de retorno de CreateJobObjectW/CloseHandle merecem revisão de ABI e teste em Windows de 64 bits. Não atribuo falha Windows reproduzida a partir desta execução Linux.

**Manifesto de bundle.** O manifesto empacotado ainda indica core_version 0.1.0.dev0, enquanto a distribuição é 0.2.0.dev0. A revisão de protocolo pode legitimamente ser a mesma; esclarecer se esse campo significa “introduzido em” ou “versão do pacote produtor”. Não alterar hashes às cegas nem tratar revisão estável como problema por si só.

**Attach, providers reais e E2.** A ausência de attach qualificado continua uma pendência conhecida, não um defeito novo surpreendente. E1 delimitado não precisa aguardar attach; já E3 não pode ser declarado sem concluir o escopo aceito. Nenhuma aprovação E2 decorre de rodar dois fakes dentro de um único processo.

## 7. Ordem recomendada de correção

1. **R01 + R02 + R03:** redesenhar como um único conjunto o fence de admissão, a guarda no efeito e a capacidade reservada de contenção. Corrigir um só desses caminhos deixa o outro neutralizar a garantia. Incluir R04 ao reorganizar deduplicação.
2. **R07:** corrigir ABI e gate de probes; repetir testes em plataforma realmente compatível. Não remover a recusa fail-closed para obter testes verdes neste sandbox.
3. **R05 + R10:** fechar limites de memória/tarefas durante carga e shutdown. A validação deve manter backlog/sink retidos, não apenas executar ciclos que esvaziam todas as filas.
4. **R06 + R08 + R09:** integrar discovery público, corrigir identidade Pi e finalizar DTOs/callbacks públicos, sem duplicar esses mecanismos nos hosts.
5. **Matriz e release:** substituir as evidências insuficientes, rerodar regressões/conformance/wheel, produzir novo artefato e reavaliar E1. Depois executar os gates E2 com Server e Connector reais; preservar pendências explícitas para E3.

Os agentes de Server e Connector podem continuar trabalho paralelo sobre o contrato com pin exato e fakes. Não devem contornar estes bloqueios copiando adaptadores ou criando um protocolo privado alternativo. Não recomendo cutover operacional do runtime enquanto os P1 persistirem.

## 8. Critérios de encerramento desta rodada

Os 14 testes deste pacote devem passar com as invariantes preservadas. Mudanças legítimas de API podem adaptar fixtures/imports, mas não apagar a falha, trocar o resultado esperado ou apenas marcar xfail/skip. Acrescentar testes reais nas fronteiras que aqui foram isoladas com peers.

Exigir: recibos idempotentes inclusive após falha, guarda no efeito físico, controles disponíveis sob saturação e journal indisponível, preflight antes de probe, recursos/tarefas limitados, build qualificado portável sem omissão de código carregável, discovery via API pública, composição pública inclusive resume. Sem prometer entrega exatamente uma vez ou parada sempre comprovável: unknown conservador continua sendo um resultado válido.

**Parecer final:** base aproveitável e evolução substancial, mas correção C1 parcial. Reabrir os itens relacionados aos achados acima; corrigir e qualificar antes de ratificar E1.

## 9. Reproduzir as evidências

Execute os comandos a partir do repositório extraído correspondente ao commit auditado, em ambiente isolado e com as dependências exatas do projeto:

```bash
python -m pip install -e '.[test]'
python -m pytest -q tests --junitxml=full.xml
python -m pytest -q tests/regression tests/test_pc*.py tests/test_offloop_executor.py --junitxml=c1.xml
PYTHONPATH=src python -m pytest -q /caminho/REAUDITORIA_CORE_E6B6305/regressoes/test_reaudit_c1.py --junitxml=reaudit.xml
```

No Windows, configurar PYTHONPATH conforme o shell. Os testes próprios não invocam providers; a suíte do projeto pode iniciar peers/processos de teste. Os dois cenários de factory/probe isolam a fronteira nativa com mocks documentados, não demonstram qualificação real de provider ou backend.

O código é sintético e usa diretórios temporários. Logs da auditoria contêm paths do sandbox e diagnósticos, não credenciais de agentes/provedores. O subdiretório evidencias contém os resultados efetivamente obtidos, inclusive falhas ambientais, e não foi editado para remover falhas.

## 10. Fontes e rastreabilidade

As fontes primárias privadas são o ZIP fornecido, o ZIP anterior, o pacote C1 e os arquivos/linhas indicados em cada achado. `evidencias/TRECHOS_FONTE.md` retém os trechos relevantes com numeração; `RESULTADOS.json` identifica hashes, contagens e achados; os XMLs ligam as asserções aos resultados. Os excertos não substituem a leitura contextual dos módulos completos.

Referências públicas técnicas consultadas: fonte oficial do Linux, include/uapi/linux/prctl.h (PR_GET_CHILD_SUBREAPER 37 e PR_GET_SPECULATION_CTRL 52); manual Linux PR_GET_CHILD_SUBREAPER(2) para a saída int*; documentação Python 3.13 de asyncio e concurrent.futures para executores/cancelamento. A distinção de protocolos MCP/nativo neste parecer deriva da decisão R3 do projeto, sem migração de transporte proposta nesta análise.

Nenhum código de produção foi corrigido, nenhum commit/push/release foi feito e nenhum segredo/provider foi utilizado. Os artefatos aqui entregues são relatório, testes e evidências, não uma versão corrigida do Core.
