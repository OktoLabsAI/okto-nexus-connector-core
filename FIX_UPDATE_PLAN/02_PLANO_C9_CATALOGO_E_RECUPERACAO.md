# C9 — catálogo público e duas correções de recuperação

**Repositório:** `okto-nexus-connector-core`  
**Referência auditada:** `6a43e90a787f3a87af8e26f3f93d4c708cf8a0a8` — `0.2.7.dev0`  
**Destinatário:** agente executor do Core; seção de integração destinada aos agentes do Server e Connector.  
**Escopo:** publicar a fonte única de runtimes para consumidores e corrigir Y01/Y02. Não reescrever a biblioteca, reabrir todos os planos nem implementar os dois aplicativos dentro do Core.

## Decisão de desenvolvimento

Server e Connector podem começar ou continuar o desenvolvimento em paralelo. O catálogo público é uma entrega prioritária de contrato para a integração do seletor. As correções de recuperação devem preceder a liberação operacional dos caminhos afetados. Consumidores não resolvem falhas copiando adaptadores ou importando membros privados.

Nesta versão, as cinco sementes originais C8 e as cinco reconstruídas pelo executor passaram. Não desfazer essas correções. As duas regressões novas falham com comportamento correto esperado. O catálogo é uma lacuna funcional confirmada pela inspeção da superfície pública, não um teste que escolheu arbitrariamente o nome de uma função inexistente.

## Invariantes

A identidade canônica é do agente e a autoridade de binding pertence ao Nexus Server. MCP existe apenas como HTTP direto entre harness e Server; Core/Connector não oferecem servidor, fachada ou proxy MCP. Stdio nativo permanece permitido. Catálogo não faz spawn, não busca credenciais e não autoriza processos. Uma instalação encontrada não comprova qualificação, e um adaptador registrado não comprova disponibilidade em determinado host.

Cancelamento da espera não prova término de thread. STOPPED não equivale a liberação durável. Sem prova de parada, conservar ownership e capacidade; sem confirmação de release, conservar obrigação. Força sobre recurso próprio deve permanecer independente de storage, encerramento gracioso e observação. Repetir shutdown não pode duplicar uma força física em andamento.

## C9-00 — Baseline e testes (antes das alterações)

### 00.1 — Registrar o estado efetivo

Registrar HEAD, branch, alterações não commitadas, versão Python/SO, dependências e hashes. Comparar com o snapshot por símbolos e testes; nunca executar reset para o commit auditado. Este pacote contém `regressoes/`, não somente Markdown. Se o HEAD já resolveu algum achado, preservar a implementação e anexar a prova.

### 00.2 — Reproduzir sem alterar a condição causal

Executar `executar_verificacao.py` com o repositório. As sementes originais C8/C7 precisam continuar passando. As duas novas regressões mantêm um observer ou um ledger retido enquanto a obrigação de controle/retorno deveria progredir. Os testes usam runtime/journal reais e peers nativos controlados, não providers reais. Restauram as barreiras no teardown.

As margens de 1,5 s para força e 3 s para retorno são envelopes de laboratório generosos frente ao shutdown `(0,0)` e cleanup de 0,03 s. Não são SLO universal. Se a correção introduzir orçamento público explícito, ajustar a fixture para aguardar além dele, documentando o diff; jamais liberar a barreira antes da asserção para obter PASS.

### 00.3 — Separar qualificações

Registrar testes unitários, fault injection, backend real, provider real e integração entre aplicativos separadamente. Não remover `require_containment` para tornar verde um ambiente incompatível. Importar `rfc8785` real no processo e nos subprocessos; não substituir por serializador aproximado. Não converter XML Windows/WSL2 recebido em uma execução realizada pelo agente de revisão.

## C9-01 — Publicar um catálogo que seja a fonte única dos consumidores

**Âncoras:** `native/registry.py`, `models.py`, `ports.py`, `__init__.py`, `runtime.py:discover`, `discovery.py`, `inventory_reducer.py`, `contracts/generate.py`, `docs/api.md`.

### 01.1 — Fonte única de metadados e API pública

Manter a implementação e o mapeamento de classes dentro do Core. Reaproveitar `_SPECS` ou mover seus dados para um módulo neutro interno. Não criar outra lista pública independente da lista de carregamento.

Publicar DTO imutável e função de enumeração documentados/exportados. Nomes sugeridos, não obrigação de quebrar nomenclatura existente: `RuntimeDescriptor`, `RuntimeCatalog`, `list_runtime_descriptors()` ou `get_runtime_catalog()`.

A consulta deve funcionar sem criar `LocalRuntimeCore`, abrir journal, possuir agente, configurar credenciais ou carregar os módulos de todos os providers. É consulta de metadados, síncrona e barata. O resultado deve ter IDs estáveis, ordem determinística, versão do formato do catálogo e versão do Core. Incluir por item pelo menos: `adapter_id`, nome de exibição, família/harness, modo de conexão nativa, modo gerenciado/attach, plataformas de implementação e estado de suporte declarado. Não expor `module`/`class_name` como parte do contrato público/remoto nem permitir import arbitrário vindo de payload.

O registro interno pode continuar possuindo nomes de módulo e classe; uma projeção pública segura os omite. Não basta exportar uma estrutura privada inteira e obrigar os hosts a conhecê-la.

**Aceite:** consumidor instalado enumera o catálogo sem imports de `native.*`; nenhuma porta ou processo é iniciado. Novo adaptador inserido na fonte única aparece na projeção sem alterar código de Server/Connector/UI.

### 01.2 — Separar adaptador conhecido, implementação e qualificação

Não usar `supported=True` como sinônimo de pronto para execução. Por exemplo, `claude_attach` está no registro, mas não qualificado; deve aparecer como indisponível/não qualificado, ou ser omitido por filtro explícito, nunca elegível apenas por existir na tabela.

As plataformas listadas em `_SPECS` indicam implementação permitida pelo registro, não evidência de contenção/provider naquele sistema. Um registro com `darwin` não autoriza READY se o backend necessário não estiver qualificado. Capacidades declaradas por família são limites superiores; capacidades efetivas vêm da instalação, versão, configuração e qualificação observadas. Preservar recusas existentes.

Os metadados de disponibilidade devem derivar das verificações e políticas do Core já existentes. Não introduzir uma nova lista de versões aceitas só para o catálogo.

**Aceite:** testes de attach desabilitado, plataforma incompatível e build não qualificado não produzem READY, mesmo com binário presente.

### 01.3 — Discovery sem lista hardcoded no chamador

Hoje `DiscoveryRequest.adapter_ids` é obrigatório e `discover()` apenas percorre esses IDs. O host precisa conhecer a lista antes de perguntar o que existe. Fornecer um caminho público para descobrir todos os adaptadores pertinentes do catálogo.

Preferir mudança aditiva: `adapter_ids=None` significa todos os que admitem discovery no host; uma tupla explícita mantém a semântica de filtro; preservar `()` como nenhum, a menos que uma alteração documentada e testada seja deliberadamente escolhida. Uma função `discover_available_runtimes()` separada também atende. O requisito é não manter array próprio no aplicativo.

Iterar o catálogo e delegar aos resolvedores existentes. Não executar attach discovery sem alvo/escopo necessário, não transformar ausência de instalação em abortar o inventário inteiro, não executar wrappers desconhecidos. Erro de uma família deve voltar como diagnóstico daquela entrada quando recuperável. Falha de autorização global permanece falha global.

**Aceite:** consumidores de teste com candidatos vazios conseguem perguntar quais famílias são conhecidas e pedir discovery sem repetir seus IDs. Filtro explícito continua limitado; IDs desconhecidos são recusados com erro tipado.

### 01.4 — Expor a avaliação local necessária ao binding

Publicar uma projeção tipada por instalação/candidato, produzida no host de execução. Nomes sugeridos: `RuntimeAvailability` / `RuntimeInventoryEntry`. Reutilizar `InstallationCandidate` sem fazer Server/Connector recalcular qualificação.

Separar dimensões: presença da instalação; plataforma; confiança local; versão/build observado; qualificação; contenção disponível; requisitos de configuração; capacidades efetivas. Preferir estados com razões estáveis como `NOT_INSTALLED`, `UNSUPPORTED_PLATFORM`, `UNQUALIFIED_BUILD`, `CONTAINMENT_UNAVAILABLE`, `PREPARATION_REQUIRED` e `READY_FOR_RUNTIME`. Esta última não significa autorização de binding do agente.

Não fazer login de provider ou abrir uma sessão para listar. Probes ativos só se explicitamente solicitados/autorizados e sob as proteções existentes. Sem observação suficiente, retornar `UNKNOWN`/`NOT_PROBED`, não inventar disponibilidade. Referências sensíveis e paths completos ficam locais; a projeção remota usa IDs opacos e metadados mínimos.

**Aceite:** uma família pode ter dois candidatos/versões no mesmo host, com estados distintos. Revalidar no prepare/open, pois o catálogo não é autorização irrevogável nem substitui detecção de drift.

### 01.5 — Remover a segunda lista manual do gerador de contratos

`contracts/generate.py` hoje repete os quatro IDs nos schemas de candidato e capacidade, além do registro. Derivar esses enums da mesma fonte de metadados ou de um snapshot versionado gerado automaticamente a partir dela. Artefatos JSON gerados podem conter cópias dos valores; eles não são outra fonte editada manualmente.

Não alterar silenciosamente contratos publicados. Fazer a primeira refatoração produzir bytes semanticamente equivalentes quando só a origem dos valores muda. Se campos de catálogo/disponibilidade atravessarem NXL, atualizar os schemas/revisão/negociação necessários e ambos os consumidores de contrato. Não afrouxar validação para aceitar módulo ou classe arbitrários.

Definir política para versões diferentes dos aplicativos: inicialmente mesmo wheel e revisão exata; depois negociação explícita. Um novo ID remoto pode ser exibido como incompatível, mas não carregado dinamicamente no Server a partir da mensagem.

**Aceite:** teste de geração comprova consistência entre registro, catálogo e schemas; alteração legítima de ID exige revisão identificável, não manutenção de arrays em dois repositórios.

### 01.6 — Contrato de consumo no Server/Connector e UI

O Core fornece fatos técnicos. O host aplicativo acrescenta `executor_id`, versão do Core, revisão do inventário e estado de conexão; o Server aplica as permissões do agente e decide binding. Não implementar HTTP, WSS ou um daemon no Core para oferecer o catálogo.

No Server local, a API do aplicativo chama o Core embutido. No Connector remoto, a CLI e o daemon consultam o mesmo Core instalado no host remoto e enviam projeção pelo canal já aprovado. O Server não usa seu próprio SO ou sua própria instalação para decidir o que está pronto na máquina remota.

A UI recebe descritores/opções da API do Nexus para o executor selecionado. Pode filtrar/ordenar/apresentar, mas não contém enum autoritativo de runtimes. Binding referencia no mínimo executor + adapter_id + candidate_id/revisão quando pertinente. Não mesclar versões por nome nem deduzir equivalência de diretórios.

OFFLINE e STALE são estados observados pelo aplicativo, não pelo catálogo estático da biblioteca. Ao desconectar, o Server invalida elegibilidade de novos bindings/inícios até reconciliação, sem apagar identidade ou histórico. Na reconexão, uma revisão nova substitui o snapshot do mesmo executor. Aplicar TTL/versão para não autorizar pelo cache antigo.

**Aceite:** adicionar metadado de adaptador de teste ao Core atualiza lista do consumidor/UI sem mudar arrays de produção; Server Linux apresenta inventário Windows remoto conforme a evidência remota, não conforme seu ambiente local. O teste de UI pertence ao Server; o Core entrega o contrato e fixtures, não executa o trabalho de outro repo implicitamente.

## C9-02 — Recuperação de força independente da observação (Y01)

**Prioridade:** P1 para a garantia de contenção.  
**Âncoras:** `runtime.py:_LateHandleRecord`, `_contain_late_open` (linhas 1736–1806), `_retry_late_handles`; coordenador de força e pools existentes.

### 02.1 — Conservar o último resultado físico e a observação separadamente

Reutilizar o registro proprietário, com referência forte ao recurso, token de ownership, tarefa produtora de força, resultado da chamada física e última observação válida. Desconhecido não é STOPPED. Depois de uma força concluída com erro e RUNNING observado, a próxima observação não pode ser um pré-requisito sem limite para permitir nova contenção.

Os recursos comprovadamente parados não devem receber força novamente. Essa decisão usa prova registrada, não aguardar indefinidamente uma consulta nova para redescobrir o fato. Se não há prova de parada e o owner continua válido, uma recuperação autorizada deve manter uma rota de força disponível.

### 02.2 — Desacoplar as tarefas de observação e força

No caminho atual, o primeiro dispatch é paralelo, mas o retry acontece depois de `await native.observe()`. Corrigir também o retry. A observação deve ter unidade possuída, coalescida e orçamento; não colocar outro `wait_for(observe)` que precise esperar cancelamento concluir para só então chamar força.

O agendamento usa estado em memória e ownership. É válido colher uma observação já disponível; se não existir resposta dentro do orçamento declarado, não bloquear indefinidamente a força sobre o mesmo recurso. Preservar pools e independência do storage.

### 02.3 — Não regredir a coalescência do C8

Antes de nova tentativa física, conferir se o produtor anterior realmente terminou. Espera cancelada não libera a marca IN_FLIGHT. Uma chamada em voo é compartilhada; uma falha física já concluída permite novo retry limitado. Atualizar estados sob seção crítica pequena, sem I/O. Evitar que dois supervisores após o mesmo observe enfileirem duas forças.

A tarefa de close também deve permanecer possuída se seu worker ainda existe. Recuperar resultados/exceções das tarefas conservadas; a prova C7 produziu log de `Task exception was never retrieved` no caminho de força que falhou, o qual deve ser eliminado como parte do lifecycle sem esconder o erro.

### 02.4 — Provar o caso e o controle

Executar `test_y01_force_retry_is_not_gated_by_stalled_observer`: primeira força falha e termina; observação posterior fica retida; segunda chamada pública consegue despachar nova força antes da liberação do observer. O teste não exige garantir morte pelo SO, só chegada ao backend/peer sob ownership correto.

Preservar a semente X03: nenhum segundo dispatch enquanto o primeiro worker estiver em voo. Acrescentar controle STOPPED conhecido: nenhuma nova força. Em SO qualificado, repetir com processo inofensivo possuído e backend real; a ausência desse ambiente é BLOCKED, não PASS.

## C9-03 — Shutdown limitado com release persistente pendente (Y02)

**Prioridade:** P2.  
**Âncoras:** `runtime.py:shutdown` (1168–1183), `_retry_release_obligations` (1841–1856), `_ReleaseObligation` e OwnedSlotLedger.

### 03.1 — Modelar release em voo e prazo de espera

A obrigação existe e deve ser preservada. Acrescentar produtor/token/estado necessários para que a liberação durável seja uma operação possuída e coalescida. O retorno do shutdown deve ter orçamento completo explícito, incluindo reconciliação; não terminar num `await` ilimitado depois de consumir os demais budgets.

Não resolver com cancelamento destrutivo da única coroutine produtora. O ledger pode continuar e confirmar o commit depois do timeout do chamador. Conservar a obrigação e observar a conclusão.

### 03.2 — Não impedir o controle de outros recursos

O shutdown atual espera `_retry_release_obligations()` antes de recuperar `_late_handles`. Um recurso parado com falha de storage não pode impedir contenção de outro ainda vivo. Agendar controles dos recursos próprios independentemente das liberações duráveis. Cumprir quotas e não criar um produtor de release por chamada pública.

### 03.3 — Relatar e reconciliar corretamente

Ao esgotar a espera, retornar relatório com a sessão identificável e uma pendência durável, sem alegar parada física desconhecida quando STOPPED já foi comprovado. Usar modelo atual se ele expressar isso inequivocamente; caso contrário fazer extensão pública mínima e documentada. Retorno vazio não significa obrigação resolvida.

Sucesso ou leitura que comprove a mesma reserva já liberada finaliza a obrigação. Erro pré-entrega permite repetir quando solicitado; confirmação perdida exige consultar/idempotência, não apagar o registro. Liberar pools físicos somente quando nenhum recurso/controle os exigir; conservar o mecanismo de recuperação durável até conclusão.

### 03.4 — Demonstrar limite e recuperação

Executar `test_y02_shutdown_budget_covers_stopped_release_obligation`: primeira falha cria obrigação; próxima liberação fica retida; shutdown retorna dentro do orçamento sem liberar a barreira do teste. Depois restaurar o ledger e confirmar liberação exata, sem spawn/força adicionais.

Acrescentar cancelamento do chamador durante commit, ACK perdido, duas chamadas concorrentes e outro recurso exigindo força enquanto o ledger está bloqueado. Não inferir rollback de timeout nem sucesso de task concluída.

## C9-04 — Integração, evidência e liberação

### 04.1 — Executar matriz sem inflar cobertura

Executar C8 original/entregue, C7 original e regressões históricas. Executar Y01/Y02 duas vezes com os controles. Mapear catálogo público ao teste por wheel e ao teste dos consumidores. Casos complementares só recebem PASS com execução correspondente; não contar cópia de XML como nova campanha.

### 04.2 — Gerar e consumir um artefato exato

Construir wheel/sdist fora da árvore de desenvolvimento, registrar hashes e instalar isoladamente. Testar import público, listagem sem I/O/spawn, conformance NXL e consumers sintéticos com mesmo wheel. Documentar versão de catálogo, contrato e eventuais changes de DTO. Não congelar nomes privados como solução transitória.

### 04.3 — Entregar aos três agentes sem bloquear trabalho independente

Core entrega primeiro o contrato público do catálogo e exemplos. Server pode desenvolver endpoint de projeção, seleção de executor, autorização e UI com DTOs/fixtures derivados desse contrato. Connector pode desenvolver daemon, CLI, importação de identidade e canal remoto. Integração de runtimes real usa o mesmo wheel corrigido; nenhum host implementa codecs de Codex/Pi/Claude.

No aceite vertical, validar primeiro um adaptador: Server+Core local sem aplicação Connector e Server remoto+Connector+mesmo Core. Depois expandir providers e falhas. Mesmo IDs/capacidades não dispensam qualificar versões e ambientes.

### 04.4 — Declarar o nível correto

Desenvolvimento paralelo está autorizado como recomendação técnica; esta auditoria não autoriza publicar release, alterar permissões, fazer push ou executar providers com credenciais reais. E1 operacional nos caminhos de recuperação depende de Y01/Y02 e qualificação pertinente. O seletor está concluído somente quando consome o catálogo público sem lista duplicada. E2 exige os aplicativos reais em dois hosts. E3 não é inferido de testes sintéticos.

Entregar resumo por achado, commit, arquivos, testes, comandos, exit codes, XMLs, hashes, limites e pendências por owner. Corrigir também afirmações documentais contraditórias sobre o catálogo, API estável e disponibilidade, sem promover implementação a qualificação.
