# Plano 3 — Criação do nexus-connector-core

**Destino:** Codex em terceiro repositório independente.
**Repositório/distribuição propostos:** `nexus-connector-core`; módulo Python `nexus_connector_core`.
**Data:** 25 de setembro de 2026. **Revisão:** 3, três projetos e MCP exclusivamente HTTP direto.
**Base de extração:** Nexus `feature/v0.2.0`, commit `7ed52c22865a92c3768bc32508ed9e35dc5efdc3` [R01].
**Consumidores:** Nexus Server e Nexus Connector. **Estado:** plano, não implementação executada.

## 1. Mandato ao Codex

> **Correção normativa r3:** MCP existe somente como HTTP direto no Nexus Server. Remover MCP stdio do Nexus; não implementar MCP stdio/HTTP, fachada ou proxy no Connector/Core. Configurar o cliente do harness não significa intermediar chamadas. Stdio nativo de runtime permanece. Esta revisão substitui r2; ver A.13.1 e J31–J34.

Crie a biblioteca Python comum que descobre, prepara, inicia, controla, observa e encerra harnesses. Extraia o código nativo existente do Nexus com seus testes/proveniência, remova dependências canônicas e complete os gaps dos adapters. A mesma implementação deve funcionar embutida no Server e hospedada no daemon Connector.

O Core é um projeto e wheel independente, preparado para PyPI, com releases próprios. Não é somente um pacote de DTOs nem um subdiretório publicado pelo Connector. Também não é servidor, daemon autônomo, cadastro de usuários/agentes, orquestrador de tarefas ou engine de handoffs.

```text
Leia este plano e os Anexos A/B. Registre o SHA real do Nexus usado na extração.
Crie a biblioteca e seus contratos em projeto independente. Preserve autoria,
licença e fixtures; não reimplemente do zero o que pode ser extraído com testes.
Não importe okto_nexus ou okto_nexus_connector no package distribuído.

K01 deve liberar o bundle de contrato; K02/K03/K04 liberam wheels incrementais
para os outros Codex. Não espere todas as integrações reais para entregar uma
API utilizável, mas mantenha gates reais NOT_RUN até serem executados.

Não publique no PyPI, não crie repo remoto nem altere licença sem autorização.
Implemente e teste; não encerre entregando só outro documento. Não declare
compatibilidade universal com harnesses/SOs não qualificados.
```

Criar `plans/implementation/` com status, backlog, decisões, matriz e evidências. Todas as tarefas/testes iniciam pendentes. O pacote de entrega deste planejamento fornece sementes legíveis por máquina.

## 2. Fronteira e dependências

Core contém descoberta, metadados de versões, preparação de ambiente, adapters, parsing/framing, processo/ownership, slots/queues, journal, normalização, controle, bridges e contratos NXL. Server autoriza colaboração; Connector administra daemon/credenciais/transporte. Core executa apenas intenções tipadas com contexto já autorizado e restrições locais.

Python >=3.11 alinha-se ao Nexus inspecionado [R02]. Evitar dependências pesadas ou obrigatoriedade de SDK de provider quando o protocolo subprocesso existente for suficiente. Base instalável/importável sem FastAPI, dashboard, torch, modelo de embedding, aplicativo Nexus ou aplicativo Connector. Dependências por SO/bridge são extras condicionais; as aplicações incluem automaticamente os extras do caminho que prometem.

Pacote não abre listener, cria event loop, modifica sinal do processo pai nem inicia tarefa de fundo em import. APIs assíncronas integram-se ao loop do host; o host controla startup/shutdown. `asyncio.run()` não aparece dentro de biblioteca chamada por loop já ativo. Operações síncronas inevitáveis usam slots finitos e cancelamento/timeout honestos.

## 3. Estrutura proposta

```text
nexus-connector-core/
  pyproject.toml
  src/nexus_connector_core/
    __init__.py               # API pública pequena e lazy
    py.typed
    models/                   # intents, receipts, events, snapshots, errors
    ports/                    # clock/journal/process/secrets/bridge/event sink
    contracts/nxl/v1/         # schemas, manifest, fixtures, hash vectors
    protocol/                 # codecs/reducers puros; sem cliente WSS de produto
    runtime/                  # lifecycle, operations, limits, reconciliation
    discovery/                # instalações confiáveis e provas versionadas
    profiles/                 # templates, realization, environment, drift
    adapters/
      codex_app_server/
      pi_rpc/
      claude_stream/
      claude_attach/
    process/                  # ownership/containment e backend de cada SO
    journal/                  # port + SQLite técnico bounded de referência
    harness_config/           # dados de cliente MCP HTTP direto; sem SDK/servidor/proxy MCP
    bridges/                  # drivers de extensão nativa não MCP, limitados
    testing/                  # peers sintéticos, fault points e conformance kit
  contracts/                  # fontes geradoras do bundle empacotado
  tests/{unit,property,contract,integration,platform}/
  docs/{api,adapters,compatibility,security}/
  plans/implementation/
```

Usar registro de adapters confiável do pacote. Plugins externos não são necessários para o primeiro release; se houver seam extensível, mensagens de rede não indicam módulos/factories a importar. Um descritor serializável pode ser consultado sem carregar dependências nativas de outro SO.

## 4. API e modelos públicos

O Anexo A fixa semântica mínima de `discover`, `prepare`, `open`, `submit`, `control`, `events`, `inspect`, `reconcile`, `close`, `shutdown`. Exportar erros tipados e resultados imutáveis. Não exigir acesso a dicionário interno do adapter, processo privado ou tabela SQLite interna.

| Tipo | Campos/invariantes principais |
|---|---|
| `AdapterDescriptor` | ID, protocolo, versões/SOs qualificados, capacidades possíveis, esquema de template |
| `InstallationCandidate` | Binário/versão/arquitetura, origem de discovery, status de confiança; sem secrets |
| `LaunchIntent` | Agente/binding/workspace lógicos, adapter/template, modo, preferência; sem shell |
| `PreparedLaunch` | Realização local, fingerprint/revisão, argv tipado, cwd validado, refs de secrets, limites efetivos |
| `ExecutionContext` | Autoridade fornecida pelo host, escopo/revisões/lease, limites; não um token de usuário Nexus |
| `Operation` | Identidade estável, hash semântico, alvo/turno esperado, ação e payload limitado |
| `OperationReceipt` | Recebimento/estágio/efeito possível, IDs, erro tipado e segurança de retry |
| `RuntimeEvent` | Identidade/sequence, categoria, nativo, correlações e payload limitado |
| `RuntimeSnapshot` | Fatos de processo/sessão/turno/bridge/lease; desconhecido não convertido em offline |
| `ReconcileReport` | Ownership, efeitos comprovados/incertos, gaps, ações locais seguras |
| `ShutdownReport` | Por sessão, drain/grace/forced/detached/unknown; nada de booleano global falso |

Ports documentadas com UoW e semântica de commit/ACK. Adapter retorna fatos nativos, kernel decide lifecycle físico e host projeta domínio. Não criar dois lugares emitindo o mesmo evento terminal. Testar evolução aditiva da API e serialização independente de plataforma.

## 5. Extração e preservação

Inventariar `src/okto_nexus/adapters/outbound/harness/*`, helpers, registry, modelos, supervisor e testes na referência. Extrair parsing, controle, environment, event buffer, compatibility e process ownership. Não copiar `MessageService`, grants, inbox, `AgentRepo`, repositórios canônicos ou o supervisor inteiro.

Para cada símbolo extraído, registrar origem/commit, dependências removidas, equivalência mantida, teste legado preservado e gap corrigido. Server poderá manter wrapper fino de compatibilidade durante migração, mas o código nativo tem um único owner após cutover.

`native_versions_tested` antigo não é evidência do novo wheel. Recuperar fixtures antigas, marcar sua proveniência e executar regressões. Testes que exigem provider são separados de testes determinísticos de protocolo. Não regravar fixture esperada só para fazer implementação divergente passar.

## 6. Descoberta, configuração e isolamento

Descoberta opera no host consumidor, não no Server remoto. Buscar candidatos por locais confiáveis/PATH/config explicitamente permitidos; tratar prioridade de cwd, symlinks e wrappers como riscos. Probes têm timeout e saída limitada; não executar binário de pasta não confiável sem seleção/aprovação.

Configurar por template: nome do adapter/provider/modelo, modos suportados, projeto, referências de auth e limites. O Core monta os argumentos obrigatórios — Codex app-server e Pi RPC, por exemplo — sem obrigar o usuário a escrever JSON de command. Paths com espaços/Unicode não podem quebrar quoting. `shell=True` ou concatenação de argumentos de rede não é solução aceitável.

Preparação não inicia trabalho produtivo. Pode executar probes isolados explicitamente delimitados. Revalidar executable fingerprint, versão, cwd, root e perfil antes do efeito. Configuração alterada entre prepare/open gera `PROFILE_DRIFT` ou reprepare seguro; não abrir com permissões ampliadas.

Credenciais de provider são resolvidas por porta local e injetadas minimamente. Não enviar login/home/secrets ao Server. Uso de home pode incluir hooks/plugins; perfil deve distinguir isso e declarar limites. Sandbox só é anunciado quando efetivamente aplicado e verificado; restringir cwd não impede acesso ao resto do filesystem por si só.

Mudanças persistentes em configuração usam plano/diff, backup, CAS e merge de campos próprios. Preferir configuração por execução. Preservar entradas MCP HTTP válidas e outros servidores; migrar somente entradas Nexus MCP stdio explicitamente selecionadas para HTTP direto, sem recriar agente/rotacionar key ou exigir reinstalação do harness.

## 7. Lifecycle, journal e recursos

Persistir intenção antes de spawn/write, estágio antes do efeito possível e fatos após observação. A janela entre efeito e commit existe: representá-la como incerteza, não eliminá-la por documentação. Mesmo ID/hash nunca dispara efeito repetido no kernel. Receipts/outcomes devem resistir a crash em cada fronteira.

Journal técnico de referência em SQLite local com migrações, locks/UoW, limites, sequence, watermarks, compaction e reserva crítica. O host pode injetar adaptação para persistência já existente, mas deve passar a mesma suite. Journal não recebe tarefas offline autônomas nem gerencia identidades canônicas. Não abrir SQLite remoto por NFS/compartilhamento como arquitetura distribuída.

Supervisionar árvore de processos próprios, stdin/stdout/stderr, async reader antes do primeiro comando, deadlines e slots. Separar stdout de protocolo e stderr diagnóstico; parsing por bytes/LF onde requerido. UTF-8 fragmentado, CRLF, U+2028/U+2029 dentro de JSON, frames enormes e saída malformada têm testes.

Processo tem birth record/guard/contenção por SO; PID isolado não é ownership. Qualificar crash entre spawn e registro, SIGKILL do supervisor, filhos/netos e PID reuse. Processo externo attach nunca entra na árvore própria para kill. Event loop do host não recebe wait bloqueante infinito.

Timeout de await não significa que thread nativa parou: contabilizar slot e estado possível até resolver. Limitar simultaneidade, bytes, filas e total de processos; controles urgentes não ficam atrás de flood de texto. Core honra drain/lease/revoke recebidos, sem renovar sua própria autoridade.

## 8. Conclusão dos quatro adapters

### 8.1. Codex app-server

Preservar conector existente e qualificar schema/handshake da versão instalada. Correlacionar requisições, thread/turn, eventos e pedidos de intervenção. Cobrir múltiplos turnos, streaming, start/resume quando suportado, interrupt, steer com turno esperado, erros e decisões de approval/input. A referência oficial distingue inicialização, thread e turno [R06]; aceitação de comando não é conclusão do trabalho.

Não expor operações nativas de shell/process spawn fora do contrato aprovado só porque o app-server as possui. Resume de conversa não prova deduplicação de efeitos. Codex é controlado pelo protocolo escolhido/qualificado, sem conexão WSS nativa pública obrigatória na máquina local.

### 8.2. Pi RPC

Preservar adapter e qualificar framing, correlação e lifecycle real. A documentação atual usa JSONL por LF, IDs de resposta e `agent_settled` para idle final [R07]. Testar versões antigas separadamente: fallback de serialização só se a versão realmente não correlacionar; não impor limitação histórica a versões novas.

Implementar prompt, steer/follow-up/abort conforme capacidades, input/extensão e bridge estruturada de ferramentas Nexus. Não habilitar `execute_work` apenas por conseguir conversar. Shutdown deve seguir protocolo qualificado e escalar controle de processo apenas se necessário.

### 8.3. Claude stream-json

Preservar adapter e qualificar modo de entrada/saída, múltiplos turnos, deltas/parciais, resultado terminal, avisos e erros [R08]. Controles/intervenções dependem da interface/versão observada, não de analogia com Codex. Não mapear interrupt enfileirado ou interrupt+reprompt para steering imediato sem declarar semântica.

Evitar sucesso fictício no intervalo entre solicitação e geração. Correlacionar request/turno, diferenciar resultado de processo e turno, não perder terminal quando stdout drena lentamente. Credenciais/sandbox mantêm o perfil autorizado.

### 8.4. Claude attach existente

Inspecionar o substrato atual antes de portá-lo, preservar capacidades demonstradas e separar ownership externo. Descoberta de alvos é explícita e scope-bound; não anexar a primeira janela/processo encontrado. Validar identidade/versão do alvo e proteção de comandos.

Se substrato for não documentado/instável, qualificar a combinação suportada e apresentar diagnóstico quando quebrar. Não habilitar capacidade desconhecida nem desativar o modo silenciosamente para aparentar conclusão. Gate específico do attach registra evidência ou bloqueio, distinto dos modos gerenciados.

## 9. Bridges e contrato compartilhado

Core é owner dos schemas NXL e da API pública, não da autenticação do Server. JSON Schemas, exemplos, hash vectors e manifest saem do mesmo build; aplicações não mantêm forks. Reducers/serialização podem ser usados por ambos sem abrir transporte.

A configuração MCP é apenas dado de cliente: URL do Nexus Server e referência segura de capability para acesso HTTP direto. O Core não instancia MCP client/server para encaminhar tools. Bridges de execução são exclusivas de integrações nativas não MCP comprovadas, com ações limitadas: Server chama domínio local; Connector usa APIs HTTPS canônicas. Não aceitar envelopes/catálogos MCP nem analisar texto livre. Aprovação não é inventada no Core.

Não há helper, extra, fachada, servidor ou proxy MCP no Core, stdio ou HTTP. Templates de configuração do cliente não exigem SDK MCP no Core. Stdio nativo dos adapters permanece e precisa de testes independentes. A extensão Pi não MCP é recurso empacotado/versionado, com fonte, build reproduzível e testes; não baixa `main` ou código remoto ao abrir runtime. Não introduzir dependência Node global adicional além da já necessária ao harness sem justificativa/instalação transparente qualificada.

## 10. Publicação e consumo

Entregar wheel/sdist e documentação da API, matriz de versões, SBOM/proveniência e hashes. Namespace, versão da biblioteca e versão NXL são distintos. Publicação em PyPI é preparada com workflow protegido, teste de instalação limpa e autorização explícita; falta de credencial de publicação não impede gerar wheel local para integrar os três projetos.

Dependências finais não usam caminho relativo para clone vizinho. Durante desenvolvimento é permitido instalar wheel local/versionado ou editable explicitamente isolado; release deve registrar hash e faixa de versão testada. Aplicações pinam minor compatível pré-1.0 e não atualizam adapters em runtime sem release.

## 11. Plano de execução por fases

### K00 — Inventariar extração e criar projeto independente

**Dependências:** Nenhuma; pode iniciar imediatamente.

**Superfícies/entregáveis:** Novo repositório, pyproject, fontes/tests Nexus e provenance.

| Tarefa | Implementação exigida |
|---|---|
| K00.1 | Registrar SHA/arquivos e dependências dos quatro adapters/helpers/supervisor do Nexus; extrair licenças/avisos e mapear código canônico que não pode migrar. |
| K00.2 | Criar distribuição/import independentes, Python >=3.11, src layout/py.typed e build wheel/sdist; nenhum daemon/servidor no import. |
| K00.3 | Inventariar testes/fixtures legados e limites documentados de protocolos/SO; distinguir evidência passada de qualificação do novo package. |
| K00.4 | Definir fronteiras de import e extras mínimos/por SO/extensão nativa não MCP; nenhuma dependência Server/Connector/dashboard/embeddings ou SDK/extra de fachada MCP. Separar stdio nativo da implementação MCP descartada. |
| K00.5 | Criar backlog/status/evidência/CI e plano de entrega incremental de wheels; não publicar/criar remote/mudar licença automaticamente. |

**Gate de saída:** Projeto independente e proveniência de extração prontos; import puro e árvore de dependências auditada.

**Testes vinculados:** TK-01, TK-02, TK-03.

### K01 — Publicar contrato normativo executável e API pública

**Dependências:** K00

**Superfícies/entregáveis:** contracts/nxl/v1, models/ports/protocol, manifest e conformance fixtures.

| Tarefa | Implementação exigida |
|---|---|
| K01.1 | Transformar Anexo A em modelos/JSON Schemas de intents, frames, eventos, erros, inventories, leases e API pública; eliminar campos de usuário Nexus. |
| K01.2 | Fixar semântica de receipts/states/ACK/unknown, generations/revisions e canonical intent hash; definir fixtures válidas/inválidas e vetores JCS. |
| K01.3 | Especificar ports Clock/Journal/Process/Secret/Bridge/EventSink e protocolos async; tipos imutáveis, contexts explícitos e nenhum segredo canônico como exigência da biblioteca. |
| K01.4 | Gerar bundle/manifest/hash e kit producer-consumer/reducers puros; empacotar resources no wheel/sdist sem download em runtime. |
| K01.5 | Entregar primeira versão de contrato aos Codex N/C, documentar breaking change e regras de atualização; consumidores verificam hash sem forks. |

**Gate de saída:** Nexus e Connector conseguem desenvolver contra mesmo bundle sem importar aplicação do outro; semântica crítica não fica em aberto.

**Testes vinculados:** TK-04, TK-05, TK-06, TK-07.

### K02 — Extrair adapters e helpers com equivalência rastreada

**Dependências:** K01

**Superfícies/entregáveis:** adapters, framing/env/event buffers, registry e testes migrados.

| Tarefa | Implementação exigida |
|---|---|
| K02.1 | Mover mecanismos nativos dos quatro adapters/helpers para tipos neutros do Core; remover imports de AgentRepo/MessageService/grants/inbox. |
| K02.2 | Criar registry confiável com metadata separada de factory, lazy load e erros de plataforma; payload de rede nunca importa módulo/factory. |
| K02.3 | Portar fixtures e regressões por adapter, registrar proveniência e comparar entradas/eventos/controles do baseline sem alterar expectativas para esconder diferenças. |
| K02.4 | Extrair helpers reutilizáveis de framing/env/eventos/ownership, evitando quatro implementações de mecanismo idêntico com semântica diferente. |
| K02.5 | Entregar wheel incremental que importa e executa peer sintético nos dois hosts consumidores; comunicar wrappers de compatibilidade permitidos no Nexus e data de remoção por gate. |

**Gate de saída:** Um único owner do código nativo com equivalência testada; wheel usável sem aplicações Nexus/Connector.

**Testes vinculados:** TK-08, TK-09, TK-10.

### K03 — Discovery, templates, auth refs e configuração segura

**Dependências:** K02

**Superfícies/entregáveis:** discovery/profiles, workspace validation e config plan/apply.

| Tarefa | Implementação exigida |
|---|---|
| K03.1 | Implementar discovery de binário/versão/arquitetura por fontes confiáveis e seleção, com probes limitados; não colher segredos ou executar candidato do cwd automaticamente. |
| K03.2 | Implementar templates de lançamento que montam argumentos obrigatórios e resolvem wrappers/paths com Unicode; sem shell livre vindo de intenção remota. |
| K03.3 | Implementar resolução de root/workspace local, fingerprint de executable/config e detecção de drift entre prepare/open; perfil não amplia sandbox implicitamente. |
| K03.4 | Implementar SecretResolver e metadados de auth/provider home/hook trust; informar auth_required sem copiar tokens ao Server ou ler todo cofre. |
| K03.5 | Implementar plan/apply de configuração efêmera/persistente com backup/CAS/merge/ownership; entregar API discovery/prepare aos hosts sem UI do Core. |

**Gate de saída:** Ambos os produtos reutilizam a mesma descoberta/realização; bug de argv não depende de correção duplicada em frontend/backend.

**Testes vinculados:** TK-11, TK-12, TK-13, TK-14, TK-15.

### K04 — Kernel, journal e lifecycle físico confiável

**Dependências:** K02

**Superfícies/entregáveis:** runtime, journal, process backends, limits/events e clocks.

| Tarefa | Implementação exigida |
|---|---|
| K04.1 | Implementar operation ledger e journal SQLite técnico por port com intenção antes do efeito, receipts/unknown e dedupe por ID/hash; teste alternativo de host adapter. |
| K04.2 | Implementar subprocess ownership/containment/birth record e encerramento de árvore por SO; diferenciar own/attach e tratar spawn-register crash/PID reuse. |
| K04.3 | Implementar leitura contínua de pipes, filas/bytes/slots limitados, priorities, evento durável/seq e reserva crítica; parsing não bloqueia loop do host. |
| K04.4 | Implementar lease monotônico, inspect/reconcile, drain/interrupt/close/shutdown report; timeout não libera slot de efeito ainda em execução. |
| K04.5 | Entregar wheel incremental com kernel/fakes/ports e fault injection kit para N03/C04; testar import/reentrância/shutdown sem daemon global. |

**Gate de saída:** Kernel embutível por ambos com durabilidade honesta, limites e cleanup demonstrados nos backends disponíveis; restante de SO declarado.

**Testes vinculados:** TK-16, TK-17, TK-18, TK-19, TK-20.

### K05 — Completar e qualificar Codex app-server

**Dependências:** K03, K04

**Superfícies/entregáveis:** adapters/codex_app_server, native schema/fixtures e provider suite.

| Tarefa | Implementação exigida |
|---|---|
| K05.1 | Qualificar binário/protocolo instalado, handshake e correlação de requests/notifications; manter schema/version matrix ao invés de presumir latest. |
| K05.2 | Implementar thread/start/resume conforme suporte, múltiplos turns/stream/events/errors; aceitação não marca trabalho concluído. |
| K05.3 | Implementar controls com alvo/turno esperado, interrupt/steer e filas limitadas; comando não suportado falha antes do efeito. |
| K05.4 | Implementar approvals/input e erros/uso que a versão realmente expõe, correlacionados ao host bridge; não habilitar shell/process features irrestritas. |
| K05.5 | Rodar contrato/fault tests e provider real autorizado, registrar versões/semântica/readiness; compare uso embutido e remoto do mesmo adapter. |

**Gate de saída:** Codex gerenciado opera com controles/eventos/approvals e resultado real; versão não qualificada é explícita.

**Testes vinculados:** TK-21, TK-22, TK-23.

### K06 — Completar e qualificar Pi RPC

**Dependências:** K03, K04

**Superfícies/entregáveis:** adapters/pi_rpc, JSONL, extension integration e provider suite.

| Tarefa | Implementação exigida |
|---|---|
| K06.1 | Implementar framing LF por bytes, UTF-8 fragmentado/CRLF/Unicode interno e leitura contínua com backpressure; stderr não é protocolo. |
| K06.2 | Qualificar echo de request IDs e respostas fora de ordem; serialização fallback só em versão delimitada que necessite, sem pressuposto universal antigo. |
| K06.3 | Implementar prompt/steer/follow-up/abort/get_state e término real qualificado, distinguindo resposta aceita e agent_settled. |
| K06.4 | Integrar pedidos extension UI/erros e hooks do bridge estruturado, correlacionando sessão/turno/input; não analisar texto como ação do Nexus. |
| K06.5 | Rodar testes de queue/retry/compaction/cancel/shutdown e provider real autorizado; publicar matriz de capacidades e limitações por versão. |

**Gate de saída:** Pi não é declarado idle no primeiro ACK/agent_end inadequado; execute_work depende do bridge K09, não somente RPC conversacional.

**Testes vinculados:** TK-24, TK-25, TK-26.

### K07 — Completar e qualificar Claude stream-json

**Dependências:** K03, K04

**Superfícies/entregáveis:** adapters/claude_stream, event normalization/control e provider suite.

| Tarefa | Implementação exigida |
|---|---|
| K07.1 | Qualificar modo de input/output da versão instalada e handshake/readiness; não inferir controles pelo nome stream-json. |
| K07.2 | Implementar múltiplos turnos, deltas/parciais, resultado terminal, erros e avisos; preservar native_type e limites de saída. |
| K07.3 | Corrigir controles em janelas requesting/generating, correlação e cancel/steer condicional; nenhuma operação no-op anunciada como sucesso. |
| K07.4 | Implementar input/approval/bridge quando protocolo suportar e sem permissões globais irrestritas; recusar capacidade indisponível honestamente. |
| K07.5 | Rodar regressões de shutdown/output drain/truncation e provider real autorizado; publicar comportamento de queue/interrupt-then-reprompt distinto de steering real. |

**Gate de saída:** Claude gerenciado completo na versão suportada, com terminal confiável e sem promises falsas de controle.

**Testes vinculados:** TK-27, TK-28, TK-29.

### K08 — Preservar e qualificar attach externo

**Dependências:** K03, K04

**Superfícies/entregáveis:** adapters/claude_attach, target identity, platform probes e detach.

| Tarefa | Implementação exigida |
|---|---|
| K08.1 | Inspecionar substrato legado integralmente, plataforma/versão e limites; portar sem adotar ou matar processos externos automaticamente. |
| K08.2 | Implementar descoberta explícita de alvos scope-bound e validação de identidade completa/TOCTOU, não primeiro PID/janela com nome parecido. |
| K08.3 | Qualificar controles/eventos realmente observáveis e erros de mudança de substrato; marcar unsupported/unqualified antes de afirmar disponibilidade. |
| K08.4 | Implementar detach/revocation/lease policy sem kill do alvo externo e sem representar existência de TUI como sessão gerenciada própria. |
| K08.5 | Rodar testes reais do substrato autorizado ou registrar blocker específico; preservar capacidade existente com gate, não apagá-la para concluir o plano. |

**Gate de saída:** Attach distinto de managed, suportado em matriz delimitada e seguro no detach; nenhuma adoção universal fictícia.

**Testes vinculados:** TK-30, TK-31, TK-32.

### K09 — Configuração HTTP direta, extensões nativas não MCP e normalização

**Dependências:** K05, K06, K07

**Superfícies/entregáveis:** templates de cliente MCP HTTP direto, extensão Pi não MCP, event schema e host ports restritas. Sem helper/SDK/proxy MCP.

| Tarefa | Implementação exigida |
|---|---|
| K09.1 | Implementar porta de ação nativa não MCP com capability/escopo para integração de harness sem cliente HTTP; rejeitar envelopes/catálogos MCP e não implementar governança canônica. |
| K09.2 | Gerar configuração declarativa do cliente MCP HTTP do harness para URL/capability do Server, local/remoto; sem SDK/fachada/proxy/subprocesso MCP, preservando entradas de terceiros e diagnosticando cliente apenas stdio. |
| K09.3 | Implementar extensão Pi nativa não MCP reproduzível/versionada no wheel, fonte/build/tests incluídos; ações explícitas, sem baixar JS de main nem servidor/bridge MCP genérica. |
| K09.4 | Integrar refs/capabilities limitadas, redaction/correlation/cancel no caminho próprio e normalizar eventos; stdio nativo continua protocolar e separado de qualquer MCP removido. |
| K09.5 | Testar configuração MCP HTTP direta e ações nativas não MCP por hosts/fakes restritos; verificar ausência de serviço MCP e qualificar execute_work somente com caminho real autorizado. |

**Gate de saída:** Templates HTTP diretos e extensão nativa não MCP reutilizados pelos dois produtos. Nenhum servidor/proxy/helper MCP; stdio nativo preservado e nenhuma chave administrativa no harness/prompt.

**Testes vinculados:** TK-33, TK-34, TK-35, TK-36, J32, J33.

### K10 — Fault injection, segurança e matriz de plataforma

**Dependências:** K04, K08, K09

**Superfícies/entregáveis:** property/fault/platform/conformance suites e performance budgets.

| Tarefa | Implementação exigida |
|---|---|
| K10.1 | Injetar crash antes/depois de spawn, journaling, write, ACK e terminal; provar estados/unknown corretos e impedir replay automático. |
| K10.2 | Qualificar grupos/guards/jobs, filhos/netos, SIGKILL do supervisor, PID reuse, logout e shutdown nos SOs; declarar limitações não testadas. |
| K10.3 | Fuzz framing/JSON/Unicode/limites, malformed provider output e input de configuração hostil; nenhum import/shell/secret leak indevido. |
| K10.4 | Rodar saturation/fairness/disco cheio/slow consumer/clock rollback, conservar controle urgente e bounded memory/journal; timeout não apaga trabalho em curso. |
| K10.5 | Executar mesmo conformance kit com journal padrão e journal host embutido, comparar traces normalizados e revisar API/import boundaries. |

**Gate de saída:** Core suporta falhas e recursos finitos com evidência por SO/protocolo; nenhuma propriedade apenas declarada em comentário.

**Testes vinculados:** TK-37, TK-38, TK-39, TK-40, TK-41.

### K11 — Release independente, documentação e integração consumidora

**Dependências:** K10

**Superfícies/entregáveis:** wheel/sdist, CI release, docs/API/compatibility e test consumers.

| Tarefa | Implementação exigida |
|---|---|
| K11.1 | Gerar wheel/sdist reprodutíveis com schemas/fixtures/bridge assets, py.typed e manifest; instalação offline do artefato não baixa contratos/código. |
| K11.2 | Rodar consumer smoke independente para EmbeddedHost e RemoteHost sem importar aplicações, e integrar builds reais N/C quando disponíveis. |
| K11.3 | Publicar docs da API, lifecycle, erros/leases/unknown, matriz de versões/SOs/bridges e migração de adapters com proveniência. |
| K11.4 | Preparar workflow PyPI protegido, checks de nome/licença/dependências/SBOM e compatibilidade; não publicar sem autorização; disponibilizar wheel local para N12/C10. |
| K11.5 | Entregar SHA/hash/API version/NXL revision e gate próprio concluído; qualificação conjunta J é registrada separadamente, sem ciclo que bloqueie entrega do wheel. |

**Gate de saída:** Biblioteca independente pronta e consumidores reais usam a mesma implementação; campanha conjunta complementa, não antecede produção do artefato.

**Testes vinculados:** TK-42, TK-43, TK-44, TK-45.

## 12. Matriz de testes específica

Todos os casos começam `NOT_RUN`. Testes de contrato/unitários e testes reais possuem registros separados quando dependem de ambientes diferentes. Nenhuma inferência a partir de mocks encerra gate nativo/multi-host.

| ID | Caso | Preparação/ação | Resultado exigido |
|---|---|---|---|
| TK-01 | Import puro | Instalar/importar base em processo limpo com auditoria de efeitos. | Sem socket/thread/processo/secret read/event loop oculto. |
| TK-02 | Deps | Examinar wheel dependency tree/import boundaries. | Sem imports de Nexus/Connector/FastAPI/dashboard/embeddings no Core base. |
| TK-03 | Proveniência | Comparar inventário de extração e licenças/fixtures. | Símbolos/testes legados rastreados e nenhum domínio canônico copiado. |
| TK-04 | API pública | Usar cliente mínimo só com exports/ports documentados. | Sem acesso a classes privadas/DB interno/global loop. |
| TK-05 | Schemas | Validar frames positivos/negativos e ação/campo de segurança desconhecido. | Rejeição correta antes de efeito e compatibilidade negociada. |
| TK-06 | Intent hash | Vetores de Unicode/ordem/retry generation e payload conflitante. | Hash semântico estável; NaN/chaves duplicadas negados e conflito detectado. |
| TK-07 | Bundle | Construir wheel/sdist e verificar resources/hash/fixture versions. | Mesmo contrato imutável disponível offline aos dois consumidores. |
| TK-08 | Extração parity | Reexecutar fixtures/testes legados por adapter. | Comportamento preservado ou mudança justificada por regressão explícita. |
| TK-09 | Registry | Peer pede module path/factory arbitrário ou adapter de SO incompatível. | Sem import dinâmico por rede; erro tipado/lazy load seguro. |
| TK-10 | Wheel inicial | Consumidor embutido e remoto fake usam artefato incremental. | Ambos executam mesma API sem instalar aplicação do outro. |
| TK-11 | Discovery | Fake executable cwd, PATH ambíguo, probe travado. | Sem execução não aprovada, timeout/limites e candidato qualificado. |
| TK-12 | Argv | Paths com espaços/Unicode/wrapper Windows para Codex/Pi. | Argumentos obrigatórios corretos sem shell montado por concatenação. |
| TK-13 | Root drift | Trocar symlink/executable/config entre prepare e open. | Revalidação nega drift/expansão antes de spawn. |
| TK-14 | Auth home | Credencial existente, login ausente e hooks/home não aprovados. | Secret ref local; nenhum broad env/home trust oculto ou segredo ao Server. |
| TK-15 | Config CAS | Editar arquivo de harness durante apply/removal. | Backup/merge/CAS preservam dados alheios e ownership de campos. |
| TK-16 | Journal efeito | Crash antes/depois de intenção e escrita nativa. | Sem replay de efeito possível; estado unknown quando necessário. |
| TK-17 | Ownership | PID reutilizado, spawn-register race e attach externo. | Nenhum kill de processo alheio; recurso próprio contido ou explicitamente incerto. |
| TK-18 | Bounded output | Flood stdout/stderr e consumidor bloqueado. | Queues/bytes finitos, leitura contínua, prioridade e gaps explícitos. |
| TK-19 | Lease/timeout | Clock rollback/reboot e await timeout de chamada síncrona. | Sem lease estendido nem slot liberado enquanto efeito continua. |
| TK-20 | Shutdown | Drain/interrupt/kill de árvores próprias e detach externo. | Relatório por sessão fiel; closing host não afeta recursos externos. |
| TK-21 | Codex lifecycle | Handshake, thread, múltiplos turns e terminal antes de ACK. | IDs/correlação e conclusão reais; processo vivo não equivale a turno ativo. |
| TK-22 | Codex control | Steer/interrupt com expected turn, stale ID e requests simultâneos. | Ação correta ou erro antes de efeito, sem atingir outro turno. |
| TK-23 | Codex HITL | Pedido de approval/input negado/tardio e provider real. | Correlação/autoridade do host preservadas; versão comprovada na matriz. |
| TK-24 | Pi framing | UTF-8 fragmentado/LF/CRLF/U+2028/U+2029 dentro de JSON. | Records não quebrados por separador Unicode; stderr separado. |
| TK-25 | Pi correlation | Respostas assíncronas fora de ordem e variante histórica. | ID correto ou serialização explicitamente qualificada por versão. |
| TK-26 | Pi settled | Prompt aceito, retries/compaction/follow-up antes de idle. | Não finaliza no ACK/agent_end prematuro; término real qualificado. |
| TK-27 | Claude stream | Múltiplos turnos/deltas/system/result com saída lenta. | Sem perda silenciosa de terminal; categorias/eventos honestos. |
| TK-28 | Claude control | Interrupt/steer durante requesting e generating. | Sem no-op positivo; semântica queue/interrupt+reprompt explicitada. |
| TK-29 | Claude HITL/erros | Pedido input/approval/erro na versão real qualificada. | Suporte efetivo demonstrado ou capability negada, sem bypass global. |
| TK-30 | Attach target | Vários processos/janelas e troca do alvo entre discovery/attach. | Só alvo escolhido/aprovado, identidade completa e TOCTOU verificado. |
| TK-31 | Attach detach | Lease/revoke/stop com processo externo anexado. | Controle desanexado; não termina alvo que não possui. |
| TK-32 | Attach compatibility | Quebrar substrato/versão/SO não qualificado. | Unsupported claro, sem capacidades inferidas ou exclusão silenciosa da feature. |
| TK-33 | Ports nativas não MCP | Hosts local/remoto usam backend restrito de ações tipadas da extensão. | Sem inbox/claim/approval na biblioteca nem envelopes MCP por essas ports. |
| TK-34 | Configuração HTTP, sem MCP runtime | Gerar configuração local/remota e inspecionar imports/extras/ports; testar cliente MCP apenas stdio. | URL/capability apontam ao Server; sem helper/servidor/proxy/SDK MCP ou command MCP; diagnóstico sem fallback e stdio nativo preservado. |
| TK-35 | Pi extensão | Instalar recurso do wheel e chamar ferramenta estruturada. | Build pinado/offline, sem fetch de main ou parsing de texto do modelo. |
| TK-36 | Capabilities | Perfil/SO/versão limita controle ou bridge. | Interseção efetiva; execute_work só com comprovação correspondente. |
| TK-37 | Fault matrix | Crash em todos os pontos instrumentados de efeito/commit. | Estado reflete o que é conhecido; não simula atomicidade com subprocesso. |
| TK-38 | SO real | SIGKILL do pai, filhos/netos, logout, jobs/guards por plataforma. | Contenção/cleanup demonstrados ou limitação explícita sem promessa universal. |
| TK-39 | Fuzz | JSON enorme/malformado/duplicado, dados provider hostis. | Sem memory blowup, shell/import de payload ou parser permissivo indevido. |
| TK-40 | Fairness | Múltiplos bindings e saturação de um stream/journal. | Limites por itens/bytes e controle urgente preservados. |
| TK-41 | Journal alternativo | Rodar conformance no SQLite default e adaptação do Server. | Mesma semântica de commit/ACK/replay/unknown, sem segundo backlog. |
| TK-42 | Packaging | Instalar wheel/sdist offline em ambientes Python suportados. | API, schemas, py.typed e assets presentes; extras separados. |
| TK-43 | Dois consumidores | Server e Connector reais usam mesmo hash de wheel. | Correção de adapter disponível aos dois, sem cópia residual. |
| TK-44 | Compat release | Atual/anterior suportado e NXL major incompatível. | Faixas documentadas/CI e recusa explícita, sem auto-upgrade do harness. |
| TK-45 | Publicação | Executar build/check/proveniência e simular ausência de credencial PyPI. | Wheel local entregue; publicação não ocorre sem autorização; status honesto. |

## 13. Governança do contrato, riscos e definição de pronto

### 13.1. Evolução do contrato e releases

O Core é a fonte única de schemas/ports/capabilities e kit de conformidade. Alteração de segurança/semântica exige ADR, versão, fixture e teste consumidor; não alterar JSON de um lado e atualizar o outro “quando der”. Nomes de classes internos podem evoluir sem mexer no contrato público. Durante desenvolvimento pré-release, negociar a revisão exata; draft r1 não é wire-compatible por omissão com agent-centric r2.

Entregar wheels incrementais em K02/K03/K04 com APIs documentadas. O gate K11 fecha biblioteca e build final; teste J de aplicações reais é evidência consumidora adicional, não dependência circular para construir o wheel. Fakes são aceitáveis no kit de contrato, não para qualificar comportamento de provider/SO real.

### 13.2. Riscos que exigem evidência, não suposição

Interfaces de harness mudam; qualificar binário/version/schema e não atualizar CLI silenciosamente. Attach pode depender de substrato instável; manter gate próprio e diagnóstico, sem elevar suporte a promessa universal. Contenção de processos varia por SO; grupos de processos não bastam para afirmar cleanup após toda forma de crash. Secret refs limitam exposição da aplicação, não isolam host comprometido.

Saturação e disco cheio impedem durabilidade infinita; reserva crítica, backpressure e parada de admissão precisam ser exercitadas. Cancelamento da coroutine não elimina efeito em processo/thread externo. Resumo de conversa e retry de tarefa são conceitos distintos; não inferir exactly-once de resume.

### 13.3. Definition of Done do Core

Biblioteca independente de fato, com wheel/sdist, API tipada, exports/documentação, import sem efeitos e dependências acíclicas. Descoberta/realização, journal, lifecycle/ownership e adapters possuem única implementação usada pelos dois produtos. Quatro adapters têm port/paridade rastreados e suporte real delimitado em matriz; modos gerenciados cobrem controles/eventos/intervenções exigidos.

Templates MCP HTTP são declarativos e apontam diretamente ao Server; o Core não implementa servidor/proxy MCP. Bridges compartilhadas são exclusivamente nativas não MCP, estruturadas, scope-bound e não implementam domínio Nexus. Schemas/fixtures/hash vetores estão empacotados; consumidores validam o mesmo bundle. Fault tests cobrem limites/janelas de efeito, sem prometer atomicidade com subprocessos ou atestação de host não existente.

Core não contém daemon de produto, usuário/AgentRepo/inbox/handoff/HTTP server. Código permanece publicável independentemente do Connector. Publicação PyPI preparada não significa que upload ocorreu; exige autorização. Uma correção de adapter vem por versão de Core e não exige duas implementações nos consumidores.

### 13.4. Entrega final do Codex

Código/ports/API, origem da extração/licença, schemas/manifest/hash, wheel/sdist e assets de bridge, fixtures/kit consumidor/fault hooks, docs/runbooks, matriz de versões/plataformas e evidência. Relatar gates reais não executados sem mascará-los; publicação/release remotos são atos separados.

---

# Anexo A — Contrato comum dos três projetos

**Revisão normativa:** `nxl-1-agent-centric-http-only-2026-09-25-r3`.
**Status:** especificação de implementação, não protocolo já disponível.
**Fonte única futura:** repositório independente `nexus-connector-core`, em `contracts/nxl/v1/`. Os três planos reproduzem este anexo a partir do mesmo texto; o manifesto do pacote registra seu SHA-256.

## A.1. Decisões que não podem ser reinterpretadas

1. O sujeito de colaboração e autorização do Nexus é o **agente canônico**. Não introduzir cadastro, login, tenant ou propriedade por usuário humano para fazer o Connector funcionar. A conta do sistema operacional que executa um serviço é apenas uma fronteira local de permissões.
2. A chave de agente já utilizada pelo MCP autentica a mesma identidade no onboarding remoto. Importar uma chave não cria um agente; escolher Codex/Pi/Claude não troca seu `agent_id`. Um identificador de Connector/executor não é um novo agente nem uma chave mestra.
3. O Nexus Server usa `nexus-connector-core` diretamente para runtimes locais. Não depende da aplicação Connector, de pareamento remoto ou de WSS em loopback. O Connector usa a mesma biblioteca para runtimes remotos.
4. Core é **terceiro projeto e distribuição Python independente**, não subpasta publicada a partir do Connector. A distribuição proposta é `nexus-connector-core`; o import é `nexus_connector_core`. Confirmar disponibilidade dos nomes antes de publicação autorizada; não mudar o limite arquitetural por conflito de nome.
5. O Connector inicia WSS para o servidor. O canal é bidirecional e controla runtimes. O único MCP do produto é o **MCP HTTP direto no Nexus Server** (Streamable HTTP compatível com o SDK/protocolo adotado). HTTPS do Connector atende autenticação/configuração, operações consultáveis, recursos e APIs canônicas não MCP; não encaminha MCP. WSS NXL não transporta nem encapsula MCP. SSE do dashboard e mecanismos HTTP existentes não precisam ser removidos.
6. `agent_id`, conexão, sessão de runtime e conversa nativa são entidades diferentes. A mesma identidade pode usar vários meios; isso não concede memória compartilhada, concorrência irrestrita ou execução duplicada de uma entrega.
7. Inbox, outbox canônica, handoffs, identidades, grants e decisões de aprovação ficam no Server. O journal técnico do executor não é outra inbox nem autoriza trabalho offline.
8. O caminho comum é configurar uma vez, reutilizar depois. Não exigir JSON, argumentos nativos, IDs de endpoint/perfil ou renovação manual de tickets por sessão. Decisões reais de segurança, instalação ausente, login de provider e mudança de escopo continuam explícitas.
9. Não desfazer trabalho posterior na branch, mudar licença, publicar pacotes ou criar repositórios remotos como efeito implícito de implementar estes planos.
10. **Remover o MCP stdio introduzido na v0.2.0 do Nexus; não preservar como legado, opcional ou fallback.** Connector e Core não oferecem servidor, fachada, proxy ou relay MCP, seja stdio ou HTTP. Quem consome MCP HTTP se conecta ao Nexus Server diretamente, inclusive no modo local.
11. Stdio de protocolos nativos de runtime permanece permitido. O transporte stdin/stdout de um adapter não se torna MCP por compartilhar esse mecanismo. Não apagar adapters nativos ao retirar o MCP stdio.
12. Configurar automaticamente o cliente MCP HTTP do harness não é intermediar suas chamadas. Nenhuma chamada MCP pode depender de processo-fachada, porta MCP do Connector, IPC do daemon ou túnel NXL. Clientes sem suporte HTTP não recebem fallback MCP stdio; diagnosticar a capacidade não suportada.

## A.2. Repositórios, dependências e responsabilidades

| Projeto | Conteúdo obrigatório | Conteúdo proibido |
|---|---|---|
| `OktoLabsAI/okto-nexus` | Domínio canônico; admissão/autorização; roteamento; executor embutido; ingresso WSS; API/MCP HTTP/CLI/dashboard; migração e remoção de MCP stdio | Implementação paralela dos protocolos nativos; dependência da aplicação Connector; resolução de paths remotos no host central; servidor MCP stdio ou shim de compatibilidade |
| `okto-nexus-connector` — novo repositório proposto | CLI; daemon; serviço de SO; armazenamento das credenciais importadas; IPC privado; cliente WSS/HTTPS para gestão; configuração do cliente MCP HTTP direto do harness | Cadastro de agentes independente; autorização de handoff offline; cópia dos adapters ou do kernel; login de usuário Nexus; servidor/fachada/proxy/relay MCP de qualquer transporte |
| `nexus-connector-core` — novo repositório | Tipos/contratos NXL; descoberta; templates; adaptadores; supervisão física; journal técnico; normalização; configuração declarativa de MCP HTTP direto; bridges nativas não MCP | Servidor Nexus; UI; daemon; autenticação canônica; WSS/HTTP de produto; política de inbox/handoff; implementação de servidor/proxy MCP ou extra MCP de fachada |

Dependências de instalação: `Nexus → Core` e `Connector → Core`. O Core não importa nenhuma das aplicações. O Server nunca importa o Connector. O Core não possui efeito colateral de abrir portas, iniciar threads/processos ou ler credenciais ao ser importado.

A implementação dos clientes WSS e das rotas HTTP pertence às aplicações; modelos, codecs, reducers e fixtures são compartilhados no Core. O armazenamento técnico possui uma implementação SQLite de referência no Core, via porta substituível. No modo embutido, o Server pode adaptar seu próprio UoW para evitar cópias desnecessárias; não misturar efeitos de processo/rede dentro de transações SQL.

## A.3. Identidade, chave e credenciais: significado exato

| Elemento | Significado e autoridade |
|---|---|
| `server_id` | Identidade persistida da instalação Nexus; não inferida somente do hostname |
| `agent_id` | Identidade canônica já existente; determinada pela credencial autenticada, não pelo JSON |
| Chave canônica do agente | A mesma credencial usada pelo MCP; armazenada no cofre local do Connector quando importada; só enviada ao servidor autorizado |
| `connector_id` | Identificador técnico persistente da instalação remota; não autentica nada por si só |
| `executor_id` | Local de execução cadastrado pelo Server; pode ser embutido ou remoto; admite apenas bindings autorizados |
| `binding_id` | Vínculo entre agente, executor, adaptador e intenção de configuração aprovada |
| `workspace_id` | Escopo lógico canônico de colaboração |
| `workspace_binding_id` | Vínculo do workspace com um diretório validado em um executor |
| `session_id` | Sessão governada de runtime; não substituir IDs de sessões históricas sem migração explícita |
| `native_session_id` / `native_turn_id` | Identificadores do protocolo do harness, subordinados à sessão governada |
| Ticket operacional | Segredo curto e limitado, emitido após autenticar a chave do agente; não nova identidade nem chave administrativa |
| Capability de sessão | Autorização limitada para MCP HTTP direto ou ações nativas não MCP; o Server valida agente, sessão e escopo. Nunca a chave canônica dentro do prompt |
| Credencial do provider | Login/API key do Codex/Claude/Pi, diferente da chave Nexus; permanece no host do harness |

O Server inspecionado guarda hash e retorna plaintext apenas ao emitir/rotacionar a chave [R03]. Portanto, **não é possível recuperar a chave atual a partir do hash**. A tela nunca deve rotacioná-la para montar um comando de conexão sem informar e obter a autorização já exigida pela gestão de chaves. Isso quebraria os MCPs que usam a chave anterior.

O fluxo obrigatório aceita importação protegida da chave existente, inclusive de uma entrada MCP explicitamente selecionada pelo operador. Não varrer arquivos, keychains ou históricos procurando segredos. Descobrir instalações/configurações candidatas não equivale a descobrir ou conceder credenciais.

Não tornar par de chaves de máquina, OAuth de usuário, SSO, conta de operador ou segunda chave persistente de agente pré-requisitos desta versão. Tickets de transporte e capabilities de sessão são detalhes internos, renovados enquanto a chave, o agente e o vínculo continuarem válidos. Rotação/revogação da chave canônica exige nova credencial válida: isso não pode ser reparado por uma renovação automática que contorne a revogação.

Preservar as superfícies administrativas existentes, inclusive eventual identidade reservada de operador. Isso não cria entidade de usuário Nexus nem autoriza entregar credencial administrativa aos harnesses.

## A.4. Fluxos normativos de configuração e uso

### A.4.1. Remoto: comando do agente para o Connector

A tela de um agente existente oferece “Conectar harness em outra máquina”. Gera comando adequado ao shell com endereço e hint do agente, sem embutir chave de longa duração em argv:

```bash
okto-nexus-connector connect --server https://nexus.exemplo --agent ag_123
```

O comando é proposto para implementação. A CLI pede a chave em entrada mascarada, aceita `--credential-stdin` para automação segura ou uma entrada MCP escolhida explicitamente. Se a interface possui a chave em memória no momento legítimo de emissão/importação, pode oferecer transferência protegida; isso não pode exigir persistir plaintext no Server nem simular recuperação do hash. O caminho garantido é chave existente por entrada protegida; não é obrigatório construir um broker de transferência de segredos nesta entrega.

O Connector valida TLS/origem, resolve `/me` pelo mecanismo de chave existente e compara a identidade retornada com o hint. Em divergência, aborta: não muda o alvo nem registra novo agente. Não baixa uma lista global de agentes. Descobre binários/configurações locais, pede seleção quando houver ambiguidade, resolve o projeto atual e apresenta **uma confirmação agregada** de agente + harness + host + projeto + permissões. Configuração técnica, perfil e endpoint são gerados de modo idempotente.

A chave é guardada como referência em cofre local, namespaced por `server_id + agent_id`; aliases são apenas nomes locais. Várias identidades podem apontar para a mesma instalação de Codex, mantendo sessões/ambientes isolados. O mesmo agente pode ter bindings distintos aprovados; isso não habilita broadcast de trabalho a todos.

`connect` pode iniciar o daemon automaticamente. Não inicia um harness apenas por descobrir ou importar a chave. `--start` ou a escolha explícita “conectar e iniciar” acrescenta a intenção de abrir runtime.

Uso recorrente, dentro da pasta do projeto:

```bash
okto-nexus-connector runtime start meu-codex
```

Sem novo cadastro, JSON ou emissão de chave. Uma troca de diretório exige apenas o consentimento definido pela política de roots, não toda a configuração novamente. Em headless, não escolher silenciosamente um agente/harness ambíguo; retornar erro acionável.

### A.4.2. Local nativo

```bash
okto-nexus serve
# Em outro terminal, no projeto:
okto-nexus runtime start ag_123 --harness codex
```

A CLI utiliza o proprietário local existente, autenticado pelo mecanismo administrativo/IPC local já confiável, e o Server produz uma execução **como o agente escolhido**, com verificação de permissões e auditoria. Não pedir que o Server recupere uma chave cujo plaintext não possui. A chave administrativa não é repassada ao runtime; gerar capability de sessão limitada.

Subcomandos de runtime podem reutilizar `--ensure-server` explicitamente aprovado para iniciar o Server quando ausente; não ativar um listener público ou configurar autostart como efeito de uma chamada MCP. Instalar o Core como dependência de `serve` e `serve-lite`; nada de instalar/parear o aplicativo Connector no mesmo host.

### A.4.3. Três intenções diferentes

`tools-only`: o próprio harness acessa diretamente o MCP HTTP do Nexus Server; não exige instalar ou executar Connector/Core. O Connector pode ajudar a escrever essa configuração, mas não participa de suas chamadas. `managed`: iniciar/reutilizar processo e sessão administrados pelo Core. `attach`: conectar-se a uma sessão existente apenas por mecanismo suportado e aprovado. A UI mostra qual ocorreu; configurar MCP HTTP não adota a conversa nativa nem transfere sua memória.

## A.5. Autorização e multiplexação no canal remoto

A autenticação de agente reaproveita o guard existente. Propor rotas HTTP abaixo, adaptando ao prefixo real sem manter serviços duplicados:

| Método/rota proposta | Entrada e efeito |
|---|---|
| `GET /v1/connections/me` | Chave de agente; retorna só identidade autenticada, permissões de conexão e revisões pertinentes |
| `POST /v1/connections/bindings:prepare` | Intenção própria, executor técnico e inventário redigido; proposta sem spawn |
| `POST /v1/connections/bindings:apply` | Proposta, revisão e aprovação autorizada; cria/reutiliza binding/endpoint/perfil em transação |
| `POST /v1/connections/bindings/{id}/ticket` | Chave do mesmo agente; ticket curto limitado ao binding e ao executor |
| `POST /v1/runtime/intents:resolve` | Binding/projeto/intenção; retorna plano de realização e status, sem executar |
| `POST /v1/runtime/operations` | Operação idempotente autorizada; 202 + recibo durável ou resultado já conhecido |
| `GET /v1/runtime/operations/{id}` | Consulta escopada; não reenvia um efeito |
| `GET /v1/runtime/executors/{id}/link` | Upgrade WSS, autenticado com ticket; subprotocolo `nxl.v1` |
| `POST /v1/runtime/approval-decisions` | Decisão autorizada e correlacionada a pedido pendente; CAS |

O Server deriva o `agent_id` da autenticação; campos de payload são hints ou assertions comparadas, nunca substitutos. Criação automática de binding só é permitida para a própria identidade e segundo políticas existentes. Ter a chave identifica o agente, mas não concede sandbox mais amplo nem desativa negações explícitas.

Por instalação/executor e Server, manter preferencialmente um WSS com lanes lógicas por binding. O primeiro ticket autentica a abertura; `binding.attach` adiciona outra lane **somente com ticket obtido pela chave daquele agente**. O canal inicialmente não conhece outros agentes. Revogar A remove autoridade de A sem conceder B nem derrubar suas sessões por acidente. Tickets não aparecem em URLs, logs, snapshots, métricas ou journal; a mensagem de attach é classificada como sensível e redigida.

Um daemon pode atender múltiplos Servers, com canais, cofres, namespaces, quotas e processos isolados por `server_id`. A implementação inicial deve suportar ao menos dois perfis de servidor na mesma máquina, sem trocar um pelo outro nem duplicar daemon. Não compartilhar credenciais entre origens; redirects de credenciais para outra origem são recusados.

Persistir `credential_epoch` e `authorization_revision` de cada binding; revogação/rotação cancela emissão e uso de tickets antigos, marca sessões sem autoridade e interrompe novas admissões. No Server online, invalidação síncrona alcança cache, lanes WSS e capacidades delegadas. Na partição, o limite é o lease local, não uma promessa de revogação instantânea.

## A.6. Workspace lógico e realização local

O path físico só é resolvido pelo host que o possui. O vínculo armazena `workspace_id`, `executor_id`, `workspace_binding_id`, `binding_revision`, root canônico local e evidência de validação. Root pode ser mantido no executor e representado por handle no Server; se for exibido, respeitar permissão e redigir nos logs gerais.

Um projeto novo pode criar workspace lógico automaticamente quando a identidade estiver autorizada. Um checkout do mesmo repositório em outro host é candidato de associação, não prova de acesso: pedir seleção/aprovação única ou usar vínculo explícito já aprovado. Git remote, branch, nome de pasta e manifestos não são identidade confiável. Não mesclar dois workspaces porque seus paths ou remotes são iguais.

Preservar IDs legados baseados em path e criar aliases/vínculos aditivos. Não re-hashear histórico nem exigir migração destrutiva para IDs UUID. Novos IDs são opacos e gerados pelo Server. APIs antigas com `project_root` local continuam por adaptador de compatibilidade; paths vindos de um cliente remoto não passam por `realpath()` no Server.

Cwd, symlinks, mudança de root, wrappers, provider homes e executable drift são verificados de novo antes de spawn, não apenas no onboarding. Root aprovado restringe realização; não equivale a sandbox do sistema operacional. Informar honestamente as restrições efetivas do harness e do SO.

## A.7. API pública mínima do Core

A API final deve ser tipada e documentada; esta é a semântica obrigatória, não implementação pronta:

```python
class RuntimeCore(Protocol):
    async def discover(self, request: DiscoveryRequest) -> Inventory: ...
    async def prepare(self, intent: LaunchIntent, context: ExecutionContext) -> PreparedLaunch: ...
    async def open(self, operation: OpenOperation, context: ExecutionContext) -> OperationReceipt: ...
    async def submit(self, operation: TurnOperation, context: ExecutionContext) -> OperationReceipt: ...
    async def control(self, operation: ControlOperation, context: ExecutionContext) -> OperationReceipt: ...
    def events(self, cursor: EventCursor) -> AsyncIterator[RuntimeEvent]: ...
    async def inspect(self, session_id: str) -> RuntimeSnapshot: ...
    async def reconcile(self, request: ReconcileRequest) -> ReconcileReport: ...
    async def close(self, operation: CloseOperation, context: ExecutionContext) -> OperationReceipt: ...
    async def shutdown(self, policy: ShutdownPolicy) -> ShutdownReport: ...
```

`ExecutionContext` é fornecido pelo host confiável após autorização canônica e inclui os limites aplicáveis, binding/revisões/lease e prova de ownership. O Core não recebe `agent_id` livre do modelo como autoridade nem valida a API key canônica. Ele aplica a interseção entre limites recebidos, aprovação local e capacidades reais.

Ports obrigatórias: relógio monotônico/parede, journal transacional, process backend, secret resolver local, event sink, approval/work bridge e resolução de artefatos. Implementações default não dependem das aplicações. `PreparedLaunch` contém argv estruturado e refs de segredo locais; nunca `shell=True` ou código executável vindo do Server. Não expor classes internas de adapter como contrato público.

O Core gera dados de configuração para o cliente MCP HTTP do harness: URL do Server e referência segura de credencial/capability. Não recebe nem encaminha mensagens MCP, não hospeda MCP e não inclui extra de fachada ou dependência MCP para esse fim. Para harness sem cliente MCP HTTP e com extensão nativa comprovada, oferece bridge estruturada **não MCP**, limitada a ações explícitas de domínio. O Server injeta backend canônico local; o Connector pode chamar as APIs HTTPS canônicas para essas ações. Essa exceção não aceita envelopes/catálogos MCP, não se aplica ao caminho de um cliente MCP HTTP e não implementa outro motor de claim/complete/approval.

## A.8. Mensagens NXL e compatibilidade

Negociar `protocol_major=1`, revisão do contrato, versão de Core, tipos de evento, limites e capacidades efetivas. Durante o desenvolvimento pré-release, exigir a revisão exata `nxl-1-agent-centric-http-only-2026-09-25-r3`; o draft anterior r1 não é aceito por possuir o mesmo major. Compatibilidade entre revisões só existe após implementação/fixtures explícitas. Major incompatível falha antes de qualquer efeito. Minor adiciona campos opcionais/tipos negociados; permissões e ações desconhecidas falham fechadas. Não atualizar automaticamente o harness ou baixar schemas de `main` em runtime.

Famílias de frame: `hello`, `welcome`, `binding.attach`, `binding.detach`, `inventory.snapshot`, `inventory.delta`, `operation.submit`, `operation.receipt`, `operation.query`, `event.batch`, `event.ack`, `reconcile.request`, `reconcile.report`, `lease.renew`, `lease.granted`, `approval.request`, `approval.decision`, `heartbeat`, `error`, `goaway`.

Envelope de operação ilustrativo (campos sensíveis não estão neste exemplo):

```json
{
  "protocol_major": 1,
  "type": "operation.submit",
  "server_id": "srv_A",
  "executor_id": "exe_B",
  "binding_id": "bind_codex",
  "agent_id": "ag_123",
  "workspace_id": "ws_456",
  "workspace_binding_id": "wb_789",
  "session_id": "rs_321",
  "operation_id": "op_abc",
  "action": "turn.submit",
  "connection_generation": 7,
  "authorization_revision": 3,
  "configuration_revision": 4,
  "intent_hash": "sha256:<64-hex>",
  "payload": {"text": "Execute o trabalho autorizado", "delivery_id": "dlv_001"}
}
```

Gerar JSON Schemas de todos os frames, intents, eventos, erros, inventário, gates de capacidade e respostas HTTP; publicar fixtures positivas/negativas. Os exemplos não substituem schema executável. Artefatos grandes usam refs autorizadas e limitadas; não interpretar URLs arbitrárias como instruções de fetch sem política de origem, tamanho e workspace.

O WSS é um canal customizado de controle do produto. O MCP HTTP direto existente permanece no SDK/protocolo já utilizado; a consulta de especificações atuais não autoriza migrar implicitamente `mcp>=1,<2` para outro major.

## A.9. Operações, deduplicação e efeito incerto

Cada intenção mutável recebe `operation_id` persistente **antes do primeiro envio**. O Server reserva operação/outbox em transação; só depois despacha. O executor grava recebimento/intenção em seu journal antes do efeito nativo. Nenhuma dessas gravações torna spawn/write nativo atomicamente transacional.

Calcular `intent_hash = SHA-256(JCS(intent))`, por implementação testada de canonicalização. O objeto semântico inclui Server/agente/binding/executor/workspace/sessão/ação/payload/revisão de configuração/turno esperado. Exclui número de tentativa, ticket, prazo de renovação e geração do canal; reconectar não muda a intenção. Não aceitar NaN, infinitos, chaves JSON duplicadas ou campos semanticamente ambíguos. Gerar vetores de hash, inclusive Unicode e ordem de campos.

Mesmo ID e mesmo hash retornam o recibo/estado conhecido, sem repetir o efeito. Mesmo ID com hash distinto gera `OPERATION_CONFLICT`. Receber um erro de rede após admissão leva a consulta/reconciliação pelo mesmo ID, nunca a novo ID automático. Trocar configuração ou pedir nova execução é uma intenção nova explicitamente autorizada.

Estágios mínimos: `RECEIVED_DURABLE`, `PREPARED`, `SUBMISSION_STARTED`, `SUBMITTED`, `ACCEPTED` quando demonstrável, `RUNNING`, `WAITING_INPUT`, e terminais `SUCCEEDED`, `FAILED`, `CANCELLED`. `OUTCOME_UNKNOWN` expressa efeito possível sem comprovação e bloqueia replay automático; não é sinônimo de falha segura para tentar novamente.

ACK WSS, write/drain de pipe, aceitação nativa, final de turno e conclusão de handoff são fatos diferentes. Se um protocolo não emite ACK de aceitação, não inventá-lo. Eventos finais podem provar conclusão mesmo que ACK intermediário tenha sido perdido; reducer aceita essa ordem sem fabricar transições observadas.

Reconciliar pode resolver um estado incerto com evidência nova; não pode declarar “não executou” apenas por timeout. Não prometer exactly-once de efeitos externos. Retry por deduplicação nativa só é permitido quando a versão do protocolo comprovar essa garantia.

## A.10. Eventos duráveis e controle sob carga

Evento recebe identidade estável `(server_id, executor_id, session_id, stream_epoch, sequence)` antes do envio. `sequence` é monotônica e persistida; `stream_epoch` não muda ao reconectar WSS. Duplicatas mantêm identidade/hash. Novo processo/sessão pode criar outro epoch explicitamente; nunca reiniciar sequência fingindo continuidade.

Categorias normalizadas: lifecycle, estado de turno, text delta/snapshot, atividade de ferramenta, approval/input request, métricas de uso disponíveis, aviso de sistema/rate limit, erro e evento nativo desconhecido. Preservar `native_type` e metadados limitados, sem rotular tudo como atividade de ferramenta. Não inventar conteúdo interno de raciocínio ausente; não armazenar segredos por diagnóstico.

ACK de eventos significa commit no ingresso durável do Server, não entrega à UI. Watermark somente contíguo; gaps pedem replay ou são explicitamente registrados quando irrecuperáveis. Projeção canônica posterior é idempotente. Após revogação, eventos antigos autenticáveis podem ser tratados como evidência histórica conforme política restrita, nunca como nova autoridade ou início de outra entrega.

Filas possuem limites por bytes e itens; fairness por binding. Reservar orçamento para interrupt, revoke, approval, ACK e terminais. Fragmentar batches de texto para que controle não aguarde frames enormes. Saturação/disk full fecha novas admissões e produz estado honesto; não descartar silenciosamente finais. Deltas podem ser compactados em snapshot com marcação explícita; dados críticos não são tratados como descartáveis.

## A.11. Ciclos de vida: daemon, runtime e turno

CLI canônica do Connector: `daemon start`, `daemon run` (foreground), `daemon status`, `daemon stop`, `service install`, `service uninstall`, `runtime start`, `runtime interrupt`, `runtime stop`, `runtime status`, `runtime logs`. Não usar `start` sem namespace para dois significados incompatíveis. Aliases de conveniência somente se inequívocos e documentados.

Daemon: `STOPPED → STARTING → RUNNING → DRAINING → STOPPED`, com `FAILED/RECOVERING` quando cabível. Uma instância por conta de SO + diretório de instalação/domínio de confiança; múltiplos agentes/Servers dentro dela. Lock com identidade real do processo e readiness via IPC; não confiar em PID file isolado. CLI e TUI podem terminar sem matar daemon/runtimes independentes. Não existe fachada MCP; uma conversa tools-only com MCP HTTP direto é independente do daemon.

`daemon start` retorna após readiness local; offline do Nexus aparece como degradação, não prova de startup falho do daemon. `daemon run` fica em foreground; Ctrl+C solicita shutdown. `service install` exige consentimento e usa serviço de usuário quando disponível, sem privilégio admin por padrão. Fechar terminal, encerrar login e reiniciar máquina são eventos distintos: sem autostart/serviço de SO qualificado não prometer sobreviver ao logout ou boot.

Não abrir todos os harnesses ao subir daemon/Server. Harness sobe por pedido explícito ou entrega cuja aprovação permita auto-start. `runtime start` reutiliza sessão compatível por padrão; `--new-session` é explícito. Readiness só depois de spawn, handshake/probe, credencial de provider e bridge necessários. Um runtime headless não implica abrir a TUI nativa em outra janela.

Interromper turno preserva runtime quando o adapter permite. Parar runtime impede novas entregas e termina recursos próprios. Parar daemon/Server entra em drain por prazo limitado, depois interrompe e encerra árvores próprias. Emitir relatório por sessão com graceful/forced/unknown; não alegar sucesso total se ownership/terminação não puder ser demonstrado. Attach externo faz detach; não matar o alvo de terceiros.

Default de shutdown explícito: aguardar até 30 s de drain, solicitar interrupção, aguardar 15 s, terminar/forçar conforme backend qualificado. Essas janelas são configuração interna validada, não requisito de um wizard. O encerramento não desfaz efeitos externos, mudanças em arquivos nem remove identidade/chave/histórico.

Política padrão de ociosidade: manter runtime reutilizável enquanto host estiver ativo, sob quota. Encerramento por idle só quando configurado e suportado; não perder silenciosamente conversa não retomável. Reiniciar processo não reenvia último trabalho. Restart com turno em andamento ou desconhecido requer política/decisão explícita.

## A.12. Partições, leases, ownership e restart

Desconexão do canal não prova morte do harness. Suspender novas operações remotas; um turno em execução pode continuar até expirar a autorização local. Heartbeat não renova lease de trabalho. O prazo local é monotônico, calculado conservadoramente a partir de validade/RTT; alteração do relógio ou replay do frame não o estende. Reboot exige revalidação antes de qualquer novo efeito.

Reconnect: TLS/autenticação, negociação, reconciliação, aplicação de revogações, renovação autorizada e só depois novas admissões. Uma operação de estado desconhecido não é realocada para outro host. O Server continua com único owner de despacho conforme a base; o projeto não implementa HA multiwriter.

`connection_generation` impede comandos de canal antigo; `session_owner_generation` protege ownership da execução. Um novo WSS não autoriza novo processo para a mesma sessão. Definir CAS para reconexão da mesma instalação; duas instâncias ativas conflitantes não alternam posse silenciosamente. Nova posse após crash exige reconciliação; clone de disco/chave não é distinguido por alegação de hostname. Não prometer atestação de hardware.

Ownership inclui PID, criação/birth record, nonce e contenção/guard por SO; não matar por PID sem comprovar origem. Qualificar Job Objects no Windows e grupos/guards/cgroups onde disponíveis nos Unix. Process groups sozinhos não garantem cleanup após SIGKILL do pai. Core deve registrar os limites efetivos e usar guard adequado ou marcar risco/indisponibilidade, nunca prometer ausência de órfãos sem teste.

Na falha do host supervisor, o default é impedir execução indefinida sem controle usando contenção/guard de processos próprios. Reabrir pipes de um processo antigo não é pressuposto. Resume de conversa nativa pode criar novo processo/sessão sob nova intenção, sem replay automático de trabalho incerto. Processo externo anexado permanece fora da política de kill.

## A.13. Capacidades reais e ferramentas Nexus no harness

Descritor do adapter informa protocolos, versões qualificadas, plataformas e semântica de controle. Capacidade efetiva é a interseção de implementação × versão detectada × SO × perfil × política × prova de readiness. Flags estáticas são metadados, não comprovação de suporte naquela instalação.

Qualificar Codex app-server, Pi RPC, Claude stream e o attach existente. Completar os modos gerenciados para multi-turn, streaming, cancelamento, erros, input/aprovações e término real. Capacidades não suportadas retornam `CAPABILITY_UNSUPPORTED` antes do efeito; não converter steering imediato em interrupt+reprompt sem sinalizar e autorizar essa semântica.

Runtimes com cliente **MCP HTTP** recebem automaticamente configuração de acesso direto ao Nexus Server, sem passar pelo Connector ou por helper MCP do Core. No mesmo host, usar o endpoint HTTP de serve; em outro host, usar a origem HTTPS aprovada e alcançável a partir do processo/sandbox do harness. Não criar entrada MCP do tipo `command/args` apontando para Nexus/Connector nem subprocesso MCP. Runtimes sem cliente MCP HTTP só usam integração nativa não MCP quando implementada e qualificada — por exemplo, uma extensão estruturada do Pi — limitada a ações dos casos de uso canônicos. Não exigir cURL manual nem interpretar texto livre como `claim`, `complete` ou autorização.

O Nexus Server emite/valida capabilities de sessão consumíveis diretamente pelo endpoint MCP HTTP; o Connector solicita a capability sob a identidade importada e o Core apenas realiza a configuração segura do cliente. Um handle IPC local não serve como substituto que obrigue proxy de chamadas. No modo local o Server não precisa recuperar plaintext de sua key armazenada como hash: emite a capability da sessão autorizada. Não confundir autenticação de lane NXL com autenticação MCP. Providers/harnesses só recebem credenciais próprias e capabilities estritamente necessárias ao processo, nunca chave administrativa ou coleção de chaves de agentes. Segredos ficam fora de prompts, logs, URLs e argv; usar referência/env/config isolada com ACL conforme capacidade real do cliente.

Modo sem bridge de trabalho comprovada pode ser qualificado como conversacional, mas não como `execute_work`. Essa limitação não pode ser ocultada para marcar adaptação completa. Para attach baseado em substrato não suportado, preservar e diagnosticar o caminho existente, qualificar versões delimitadas; não inventar compatibilidade universal.

## A.13.1. Topologia MCP HTTP, credenciais diretas e remoção do stdio

A correção de arquitetura é normativa e substitui qualquer instrução de preservar stdio, criar fachada ou oferecer MCP dentro do Connector/Core nas revisões anteriores. Ela não é uma opção de implantação.

```text
Ferramentas — harness com MCP HTTP, local ou remoto:
  Harness (cliente MCP HTTP) ── HTTP(S) direto ──> Nexus Server / endpoint MCP

Controle remoto de runtime:
  Nexus Server <── WSS / NXL ──> Connector + Core <── protocolo nativo ──> Harness

Controle local de runtime:
  Nexus Server + Core <── protocolo nativo ──> Harness
```

O caminho de ferramentas não atravessa o processo Connector/Core. O caminho de runtime não é MCP, ainda que o adapter nativo use stdin/stdout. O Server precisa estar rodando para servir MCP HTTP; o harness não inicia uma instância Nexus por configuração MCP `command`. IPC privado da CLI/daemon permanece permitido para gestão, nunca como endpoint MCP. HTTP(S) de gestão no Server e o cliente HTTPS do Connector continuam válidos; não confundir remoção de MCP no Connector com proibição de todo uso de HTTP.

**Autoconfiguração e independência.** Preservar conexões MCP HTTP já existentes e a identidade do agente. Para novas configurações, gerar URL alcançável no contexto real do harness — não reutilizar loopback do Server para um host remoto, e considerar container/sandbox e allowlists de rede aprovadas. Preferir configuração por sessão; persistente usa consentimento, diff, backup e CAS. Não instalar MCP server/proxy local, não expor porta MCP no Connector, não injetar catálogo MCP em NXL e não introduzir callbacks para o daemon a cada tool call. Um cenário tools-only configurado com a credencial atual funciona sem instalar Connector, e continua funcionando após desligá-lo se ele foi usado apenas para configurar; isso não promete manter vivo um runtime que o daemon possui quando ele é desligado.

**Autorização direta.** O endpoint MCP HTTP resolve o agente pela credencial/capability autenticada e aplica permissões, claims e deduplicação comuns. Managed sessions recebem capability limitada por agente/workspace/binding/sessão/ações e validade; a identidade permanece o mesmo agente, não nasce outra credencial canônica. Requisições MCP diretas não podem contornar lease, geração, grants ou revogação das operações que pertencem à sessão gerenciada. A credencial canônica de um cenário tools-only independente mantém a política própria já existente; possuir WSS não é requisito para usar MCP HTTP legítimo.

**Validade sem proxy.** Tickets NXL e capabilities MCP têm finalidade e audiência distintas. Especificar e testar emissão, expiração, renovação e revogação das capabilities no Server. Preferir segredo de sessão validado contra estado/validade renovável no Server, sem reinjetar segredo a cada chamada; não pressupor hot-reload de credenciais em todos os harnesses. Qualificar o mecanismo seguro por adapter, inclusive expiração durante turno. Não trocar uma operação incerta por restart/retry para renovar credenciais. O modo tools-only independente não depende do Connector para renovar sua credencial; revogação real exige o fluxo autorizado. Nunca aceitar automaticamente um ticket NXL como bearer MCP com escopo ampliado.

**Partições independentes.** Testar WSS indisponível com HTTP alcançável e o inverso. A perda do WSS não redireciona MCP via túnel nem autoriza novos efeitos de sessão após lease/revogação. A perda do MCP HTTP não é reparada com MCP stdio; reportar disponibilidade separada de processo, controle e ferramentas. `execute_work` exige caminho de ferramentas e autorização comprovados; runtime conversacional não deve ser anunciado como execução governada completa. Capability expirada não vira falha segura para repetir uma chamada mutável.

**Migração obrigatória.** Inventariar e remover entrypoints, subcomandos, inicialização automática por harness, módulos, distribuição, exemplos, wizard, documentação e testes que implementam ou mantêm MCP stdio no Nexus. Comando antigo deve falhar de forma prescritiva ou deixar de existir, sem abrir transporte MCP nem preservar um shim stdio→HTTP. Converter somente configurações Nexus explicitamente selecionadas e sob ownership/consentimento; manter identidade/key e entradas de outros servidores MCP. O rollback deste trabalho não reativa MCP stdio como fallback operacional; uma volta manual a artefato histórico é um downgrade fora do contrato r3, nunca suporte aceito. Remover a implementação não autoriza apagar projetos/histórico ou adapters nativos de stdio.

**Capacidade não suportada.** Harness com MCP apenas stdio não atende ao caminho MCP desta arquitetura. Retornar diagnóstico de transporte não suportado, sem instalar proxy de terceiros nem extensão genérica que apenas esconda o mesmo proxy. Uma integração nativa não MCP é uma feature separada, limitada, estruturada e qualificada; não recebe envelopes MCP, não publica MCP e não substitui o caminho direto de harness compatível.

## A.14. Inbox, respostas, handoffs e HITL

Uma entrega lógica disputa o mesmo mecanismo de consumo exclusivo entre MCP pull, runtime local e runtime remoto. A outbox registra tentativas de transporte; não vira segunda tarefa. Duplicar conexão não duplica grant, turno ou resposta. Observadores recebem eventos sem execução; não enviar prompt de trabalho a um “observador” que o executará.

Turno concluído não significa handoff concluído. O resultado governado passa pelos casos de uso de claim/grant/complete existentes. Preservar reply target, root/parent/correlation, dedupe, orçamento causal/relay e evidências. Reconnect não reinicia orçamento de mensagens nem permite loop de agentes.

Pedido HITL correlaciona binding, sessão, turno, request nativo, geração, revisão e expiry. Server autoriza/registra decisão única com CAS; UI e CLI são canais de apresentação, não identidades humanas novas nem autoridades paralelas. A chave do próprio agente não basta para aprovar uma escalada que exige operador. CLI deve encaminhar ao mecanismo já autorizado ou reportar pendência; jamais autoaprovar por ser local.

Negação, timeout, saída da UI ou rede caída não viram aprovação. Resposta tardia não é aplicada a outro turno. Estado de solicitação e decisão precisa sobreviver ao reconnect dentro das capacidades reais do harness.

## A.15. Segurança, isolamento e configuração

Cofre local para chaves; configuração/journal guarda refs. Fallback restrito com ACL é explícito e explicado, sem alegar criptografia que não existe. Host comprometido ou processo malicioso com a mesma conta do SO pode exceder a proteção da aplicação; sandbox de provider não equivale a isolamento de contas. Redigir secrets em stdout/stderr, tracing, dump e exports; evitar dumps de memória por padrão.

Não procurar credenciais automaticamente. Detectar métodos locais de autenticação, disponibilidade de login e arquivos candidatos; ler/importar só o que foi selecionado. Provider homes podem carregar hooks/plugins: consentimento de usar login não é autorização de executar todo hook do home. Resolver isolamento/config suportado por versão e informar quando não puder separar.

Alterações em configuração de harness são plan/apply com backup, comparação de revisão e merge estrutural. Preferir configuração efêmera por execução. Não sobrescrever arquivos globais ou apagar entradas de outros MCPs. `disconnect/unbind` remove somente campos sob ownership do produto; evidência de operações não é apagada como efeito de remover configuração.

Não aceitar executable, argv arbitrário, env livre, plugin dinâmico ou root enviado pela rede como autorização. O Server envia intenção/template; Core resolve realização local aprovada. Wrapper Windows deve ter implementação especializada/qualificada, não comando de shell montado por concatenação.

TLS obrigatório fora de desenvolvimento loopback explícito, sem fallback silencioso `verify=False`. Allowlist da origem, proteção de proxy reverso, limites de frame, redaction de headers e timeout de upgrade. Não expor IPC à rede externa. Unix sockets/named pipes com ACL; fallback loopback só autenticado e com proteção de origem/CSRF onde aplicável.

## A.16. Defaults, escalabilidade e observabilidade

Defaults são hipóteses de engenharia a testar, não resultados de benchmark:

| Parâmetro | Default inicial |
|---|---|
| Ticket de binding | 10 min, renovação a 70% com jitter e single-flight |
| Heartbeat / detecção de canal ausente | 15 s / 45 s; ausência não prova término do runtime |
| Lease de sessão / renovação | 120 s / 30 s; renovação condicionada à autorização |
| Grace após lease | 15 s antes de escalada de terminação própria |
| Startup de runtime | Até 90 s; API pode responder 202 imediatamente |
| Frame máximo / chunk de evento | 1 MiB / 64 KiB, medidos em bytes |
| Intenção inline | 64 KiB; recursos maiores por referência autorizada |
| Operações em trânsito / runtimes por instalação | 32 / 8, respeitando política e quotas existentes |
| Journal técnico por executor | 256 MiB, 16 MiB reservados para controle/críticos |
| Backoff de rede | 0,5–30 s exponencial com jitter; não é retry de efeito |
| Drain explícito | 30 s + 15 s de grace; resultado por recurso |

Ao atingir 80% do journal sem recuperação saudável, bloquear novas admissões e compactar somente dados elegíveis. Quotas por agente/host/Server contam todos os endpoints; fairness impede um stream monopolizar o daemon.

Cenário de pelo menos **100 mil identidades cadastradas**: onboarding autentica uma chave por índice e retorna somente vínculos pertinentes; descoberta é local. Não enumerar todas as identidades, abrir WSS para agentes offline ou alocar uma thread por agente cadastrado. Paginação por cursor, índices e caches limitados. Volume de identidades não é promessa de 100 mil runtimes concorrentes; medir concorrência separadamente.

Métricas: tempo de resolve/start/ready, reconexão, backlog em bytes, leases, gaps, operações incertas, duração de approval, recursos por adapter. Não usar `agent_id/session_id` como labels ilimitados de métricas; IDs completos ficam em logs/traces escopados e redigidos. WSS ativo, daemon vivo e runtime pronto são estados distintos.

## A.17. Erros, compatibilidade e publicação

Erros mínimos: `AGENT_AUTH_REQUIRED`, `AGENT_ID_MISMATCH`, `AGENT_REVOKED`, `CREDENTIAL_REPLACEMENT_REQUIRED`, `SERVER_ID_CHANGED`, `BINDING_NOT_AUTHORIZED`, `AMBIGUOUS_BINDING`, `APPROVAL_REQUIRED`, `PROVIDER_AUTH_REQUIRED`, `BINARY_NOT_FOUND`, `NATIVE_VERSION_UNQUALIFIED`, `PROFILE_DRIFT`, `WORKSPACE_UNAVAILABLE`, `EXECUTOR_OFFLINE`, `STALE_GENERATION`, `STALE_TURN`, `CAPABILITY_UNSUPPORTED`, `OPERATION_CONFLICT`, `OUTCOME_UNKNOWN`, `JOURNAL_FULL`, `EVENT_GAP`, `CAPACITY_EXCEEDED`, `VERSION_INCOMPATIBLE`.

Resposta inclui código, estágio, possível efeito, segurança do retry, operation_id consultável e ação corretiva. Não ecoar segredo, traceback ou root sem necessidade. Erro de rede depois de efeito possível não pode receber `retry_safe=true`.

Core usa SemVer da biblioteca, separado do wire major NXL. Antes de 1.0, fixar minor compatível e testar upgrade explicitamente. Aplicações consomem wheel imutável + hash; nada de instalar `main` ou importar pasta irmã como distribuição final. Schemas e fixtures fazem parte do wheel e sdist. Publicação PyPI é etapa técnica preparada, mas só executada com autorização e credenciais apropriadas; build local não depende disso.

Não alterar a licença dos arquivos extraídos sem decisão do titular. Preservar avisos/proveniência e registrar necessidades de packaging/licença sem transformar este plano em parecer jurídico.

## A.18. Ordem dos três projetos e evidência

O Core é dono dos contratos; N00, C00 e K00 podem começar em paralelo. K01 publica bundle de desenvolvimento a partir deste anexo. K02/K03/K04 liberam wheel incremental utilizável antes de terminar todos os adapters. Nexus e Connector integram esse wheel; não esperam conclusão total do outro projeto.

```text
N00 ───────────────┐
C00 ───────────────┤
K00 → K01 ────────┼→ N01/N02 e C01/C02
       → K02 → K03/K04 → N03/N04 e C03/C04/C05
                         → K05/K06/K07/K08 → K09 → bridges nas aplicações
N05/N06 + C04 → primeiro WSS ponta a ponta
N12 + C10 + K11 → mesma campanha conjunta N13/C11
```

Dependências cruzadas de testes são **gates de integração**, não exigência de um projeto se declarar DONE antes do outro rodar a mesma campanha. Cada build registra SHA de Server/Connector/Core e hash do bundle.

Nenhuma evidência de teste executado durante a escrita destes planos é presumida. Tarefas começam `PENDING`; testes `NOT_RUN`. Codex pode usar fakes para unitários/contratos, mas testes de provider real, múltiplos hosts e processo/SO precisam executar nesses ambientes. Sem credencial/host autorizado, registrar bloqueio externo e continuar tarefas independentes; não declarar o produto completo com mocks.

Cada evidência inclui ID, ambiente, versões, comandos, resultado, logs redigidos, duração/recursos quando relevantes e distinção entre falha anterior e regressão. Não sobrescrever evidência histórica. Implementar, testar e registrar resultados; não encerrar entregando outro planejamento.

---

# Anexo B — Aceite conjunto dos três projetos

Os casos abaixo são os mesmos nos três planos. Todos iniciam **NOT_RUN**. Registrar owner de execução, ambiente e blockers. Um cenário de contrato com peer sintético não fecha o cenário homônimo que exige provider/host/SO real.

**Topologia mínima:** A com Nexus Server sem binários/provider keys/projetos remotos; B/C com Connector e o mesmo wheel Core; uma instalação Nexus local separada sem aplicativo Connector. Para heterogeneidade, incluir Windows e um Unix em infraestrutura autorizada. Não simular SO só mudando uma string `platform`.

| ID | Cenário | Preparação/ação | Resultado exigido |
|---|---|---|---|
| J01 | Identidade canônica | Criar agente previamente no Nexus e configurar MCP com sua key; importar a mesma no Connector. | Nenhum segundo Agent/user; MCP continua válido, mesmo agent_id em mensagens e sessões. |
| J02 | Não rotacionar para conectar | Usar Server que guarda somente hash; gerar comando para identidade existente. | Comando pede/importa key existente de forma protegida; não chama issue_key silenciosamente. |
| J03 | Autenticação errada | Key A com hint B; depois ticket A tenta abrir lane de B. | Negação antes de configuração/spawn; nenhuma atribuição por payload. |
| J04 | Nexus local puro | Instalar Nexus/Core, sem app Connector, e abrir/gerir cada runtime gerenciado qualificado. | Core embutido em serve, sem daemon Connector, pareamento ou WSS local obrigatório. |
| J05 | Servidor realmente remoto | A sem executáveis/providers/projetos; B/C com Connector/Core e harnesses. | Operações e streams funcionam; Server não faz realpath/spawn de B/C. |
| J06 | Rede outbound | Firewall de B/C nega conexões entrantes e permite WSS/HTTPS ao Server; testar também o processo/sandbox do harness. | Controle via Connector e MCP HTTP direto via harness funcionam com tráfego de saída; nenhuma porta MCP local exigida. |
| J07 | Paths heterogêneos | A Linux, B Windows e C Unix; roots diferentes do mesmo e de outros repositórios. | Vínculos lógicos autorizados, validação física local e nenhuma fusão por path/Git. |
| J08 | 100 mil agentes | Sem providers, popular 100 mil identidades no Server e importar uma key em B. | Queries indexadas e escopadas; não listar tudo nem criar recursos por agente offline. |
| J09 | Um daemon, várias identidades | B importa agentes A1/A2 que usam o mesmo binário Codex e um agente Pi. | Sessões/credentials/lanes isoladas, sem daemon por agente ou prompt broadcast indevido. |
| J10 | Dois Servers | B conecta dois Servers distintos e remove/revoga binding em apenas um. | Namespaces, processos, cofre e tickets do outro preservados. |
| J11 | First-use/second-use | Configurar por comando da tela e executar runtime start repetidamente. | Setup agregado uma vez; depois sem JSON/argv/endpoint/profile/grant/chave manual recorrente. |
| J12 | Daemon automático | Connect e runtime start concorrentes com daemon parado. | Uma instância; daemon ready não abre todos os harnesses descobertos. |
| J13 | Terminal independente | Fechar CLI de start, TUI/log follower e encerrar cliente MCP HTTP tools-only independente. | Daemon e runtimes independentes continuam; fechar cliente HTTP não encerra supervisor nem outra sessão. |
| J14 | Turno versus processo | Enviar trabalho, interrupt, novo turno e runtime stop. | Cancelamento preserva runtime quando suportado; stop encerra recursos próprios, não identidade/histórico. |
| J15 | Shutdown/crash | Stop daemon/serve; depois SIGKILL do supervisor em cenário controlado. | Drain/containment e relatório real; sem kill alheio ou trabalho indefinido não declarado. |
| J16 | MCP HTTP tools-only direto | Usar conversa não gerenciada com MCP HTTP antes/depois de instalar e desligar Connector; também testar sem Connector instalado. | Harness chama somente o Server; identidade preservada, nenhum proxy/subprocesso MCP e nenhuma adoção de conversa pelo runtime. |
| J17 | Work bridge nativa não MCP | Pi sem MCP HTTP recebe tarefa e chama contexto/claim/complete via extensão qualificada. | Mesmo domínio canônico; nenhum servidor/proxy/envelope MCP no Core/Connector; texto livre não completa handoff. |
| J18 | Consumo exclusivo | Uma entrega com MCP pull e dois runtimes disponíveis ao mesmo agente. | Um consumidor lógico; sem duplo turno/grant/resposta por multiplicidade de conexão. |
| J19 | HITL concorrente | Provider pede aprovação; CLI/UI respondem, agente tenta autoaprovar e decisão chega tarde. | Autoridade existente, CAS, geração/turno corretos; timeout/deny não aprovam. |
| J20 | Recebido não é concluído | Observar ACK WSS, aceitação nativa, fim de turno e handoff em cada adapter. | Estados separados, nenhum marco antecipa outro sem evidência. |
| J21 | Resposta perdida | Perder ACK após submit nativo possível, reconectar e repetir consulta/ID. | Sem replay automático; recibo/unknown/reconciliação pelo mesmo intent. |
| J22 | Partição e revogação | Revogar key com WSS online e depois testar partição prolongada/relógio alterado. | Online invalida derivados; offline limita por lease, sem prometer revogação instantânea. |
| J23 | Gerações e takeover | Canal antigo e novo/daemon clonado disputam mesma sessão. | Um owner, fencing/reconciliação; sem failover silencioso ou processo duplicado. |
| J24 | Eventos/retention | Interromper ACK, enviar duplicatas/out-of-order e ultrapassar retenção. | Ingressão durável idempotente e watermark contíguo; gap explícito, terminais não ocultos. |
| J25 | Saturação | Flood texto, disco cheio e consumidor lento enquanto chega interrupt. | Memória/journal/queues finitos, faixa crítica preservada e novas admissões bloqueadas quando necessário. |
| J26 | Drift/config segura | Trocar binary/root/symlink/home/hook e editar MCP existente durante setup. | Reprepare/approval/CAS; sem execução ampliada, JSON destruído ou secrets centrais. |
| J27 | Quatro adapters | Qualificar Codex/Pi/Claude managed e attach existente por versão/SO delimitados. | Mesma implementação Core local/remota e capabilities comprovadas, sem sucesso simulado. |
| J28 | Upgrade/rollback | Migrar Nexus legado, atualizar Connector/Core com journal pendente e instalar wheels limpos. | Histórico/IDs/negações preservados, drain/reconcile e dependências acíclicas. |
| J29 | Segredos/ameaças | Inspecionar argv/log/config/export/metric; tentar handle/agent/server spoof e shell injection. | Sem chave canônica/admin de terceiros/provider secrets vazados ou efeito fora do escopo. |
| J30 | Release coordenado | Conferir resultados/SHAs/wheel hashes e gates provider/SO/multi-host em três relatórios. | Mesma evidência, bloqueios explícitos e nenhuma alegação de produto completo baseada só em fakes. |
| J31 | Remoção MCP stdio | Instalação limpa e upgrade do Nexus v0.2.0 com configuração MCP stdio; inspecionar entrypoints, módulos, exemplos e migração selecionada. | MCP stdio ausente, sem shim/fallback; MCP HTTP direto mantém agente/key/histórico e outras entradas não são alteradas. |
| J32 | MCP HTTP local nativo | Somente Nexus/Core no host; abrir runtime gerenciado com MCP HTTP para o próprio Server. | Sem Connector ou fachada; cliente chama endpoint HTTP de serve com capability válida e o Core só configura o cliente. |
| J33 | Fronteira protocolo/transporte | Exercitar stdio nativo dos adapters e inspecionar artefatos/portas de Connector/Core; testar harness com MCP apenas stdio. | Protocolos nativos funcionam; nenhum serviço/extra/CLI MCP/proxy; cliente incompatível recebe diagnóstico sem fallback stdio. |
| J34 | Dois canais e autorização | Em runtime remoto com MCP HTTP direto, derrubar apenas WSS e depois apenas HTTP; expirar/revogar capability e manter outra conversa tools-only independente. | Sessão gerenciada respeita lease/grants/revogação sem bypass, replay ou túnel; canal HTTP tools-only legítimo mantém política própria sem exigir daemon. |

## Registro de evidência obrigatório

Cada caso registra: `test_id`, `status`, `blocked_reason`, SHAs de Server/Connector/Core, hashes dos wheels/bundle, versões dos harnesses, SO/arquitetura, topologia e política, comandos exatos, data/hora, resultado observado, artefatos redigidos e limitações. Status permitido: NOT_RUN/PASS/FAIL. Não usar SKIP como sinônimo de PASS.

Segregar credenciais/contas e projetos de teste. Não executar faturamento/provider/hosts de produção sem autorização. Quando indisponíveis, construir fixtures e registrar contrato PASS se executado, mantendo o caso real NOT_RUN. Um relatório de CI verde com testes reais não executados não autoriza alegar suporte nesses ambientes.

A campanha N13/C11 pode começar assim que N12, C10 e K11 entregarem seus artefatos. Nenhuma fase aguarda que a outra conclua a mesma campanha. Reutilizar a mesma evidência, não dois resultados conflitantes com SHAs diferentes.

---

# Anexo C — Fontes, baseline e natureza das decisões

## C.1. Referências históricas da revisão 2

**[R01]** GitHub, branch `feature/v0.2.0`: HEAD `7ed52c22865a92c3768bc32508ed9e35dc5efdc3`, registrado como confirmado na revisão 2 em 25/09/2026. A revisão 3 não consultou novamente o repositório; o Codex deve conferir o HEAD efetivo.
https://api.github.com/repos/OktoLabsAI/okto-nexus/branches/feature/v0.2.0

**[R02]** `pyproject.toml` no SHA de referência: Python >=3.11; dependência MCP `>=1.0,<2`; extras serve/serve-lite; CLI e metadados do projeto. Não mudar SDK major ou licença como efeito da extração.
https://github.com/OktoLabsAI/okto-nexus/blob/7ed52c22865a92c3768bc32508ed9e35dc5efdc3/pyproject.toml

**[R03]** `application/auth.py`: AgentKeyAuthService, emissão/rotação, hash, retorno de plaintext uma vez, resolvedor e invalidação. Importação de chave existente e tickets derivados são decisões de projeto; não supor que já estejam implementados.
https://github.com/OktoLabsAI/okto-nexus/blob/7ed52c22865a92c3768bc32508ed9e35dc5efdc3/src/okto_nexus/application/auth.py

**[R04]** `application/identity.py`: identidade/sessões/workspaces e caminho legado de resolução física do project_root. As demais âncoras de runtime/UI vieram da revisão anterior e precisam ser reproduzidas pelo Codex no HEAD efetivo.
https://github.com/OktoLabsAI/okto-nexus/blob/7ed52c22865a92c3768bc32508ed9e35dc5efdc3/src/okto_nexus/application/identity.py

**[R05]** Materiais anteriores fornecidos nesta conversa e relidos a partir de seus arquivos: `PLANO_01_NEXUS_CONEXOES_NATIVAS_E_DISTRIBUIDAS_CODEX.md` e `PLANO_02_NEXUS_CONNECTOR_CODEX.md`, contrato `nxl-1-draft-2026-09-24-r1`. Foram usados como base/crosswalk, não como autoridade acima das decisões posteriores. Esta revisão substitui o desenho de dois projetos, o runtime package dentro do Connector e onboarding não centrado na credencial do agente.

## C.2. Referências técnicas primárias registradas na revisão 2

**[R06]** Documentação oficial do Codex App Server, consultada em 25/09/2026. O endereço redirecionou para documentação oficial em ChatGPT Learn. Usar a versão instalada e schemas do binário como parte da qualificação; não prometer todos os recursos descritos para versões antigas.
https://developers.openai.com/codex/app-server/
https://learn.chatgpt.com/docs/app-server

**[R07]** Documentação RPC do Pi no repositório oficial atual `earendil-works/pi`; o antigo endereço `badlogic/pi-mono` redireciona. Arquivo consultado pelo GitHub, blob `ad6ff90e80ba89eb2a42f226c1cbd46bc1818a2f`: framing LF, IDs assíncronos, eventos e shutdown. Fixar commit/versão usados nos testes de implementação.
https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md

**[R08]** Documentação oficial Claude Code, uso programático e saída stream-json, consultada em 25/09/2026. Controles/approvals devem ser verificados na interface e versão qualificada, não inferidos da saída em streaming.
https://code.claude.com/docs/en/headless

**[R09]** Especificação MCP versionada 2025-11-25, usada para Streamable HTTP. A presença de stdio no padrão não autoriza MCP stdio nestes produtos; r3 o proíbe. Referência deliberadamente versionada para compatibilidade, não afirmação de que é a revisão mais recente. O plano não migra o protocolo/SDK da base implicitamente.
https://modelcontextprotocol.io/specification/2025-11-25/basic/transports

**[R10]** RFC 6455, WebSocket. NXL é decisão de protocolo do produto sobre WSS, não parte do padrão MCP.
https://www.rfc-editor.org/rfc/rfc6455

**[R11]** Decisão explícita do usuário nesta conversa, 25/09/2026: remover MCP stdio do Nexus e qualquer MCP no Connector; clientes MCP acessam diretamente o Nexus Server por HTTP. A revisão 3 corrige documentos e backlogs, sem nova auditoria de código ou consulta às fontes externas. Essa decisão prevalece sobre instruções de compatibilidade stdio/fachada da revisão 2.

## C.3. O que é especificação, não fato implementado

Nomes/rotas novos, comandos CLI, modelos, API do Core, tickets, defaults, budgets, schemas a gerar, fases, testes e métricas são decisões propostas e requisitos de implementação. Nenhum benchmark, teste de provider, execução multi-host, publicação PyPI ou alteração em repositório foi realizado ao escrever estes planos. A validação desta entrega verifica consistência dos documentos/backlogs, não funcionamento do produto.

Se o HEAD mudou, o Codex registra a diferença e aproveita código correto posterior; não restaura a branch ao SHA deste documento. Conflitos com limites reais de protocolo devem produzir ADR, capacidade explícita e teste, não uma promessa inexequível ou remoção silenciosa de requisito.
