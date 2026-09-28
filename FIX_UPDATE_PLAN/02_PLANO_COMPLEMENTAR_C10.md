# C10 — concluir a disponibilidade pública e preservar produtores duráveis no shutdown

**Repositório:** okto-nexus-connector-core.  
**Snapshot revisado:** `c5bd9557861f44577ae8dbf5585790acfd045fa5`, pacote `0.2.8.dev0`.  
**Referência de requisitos:** C9-01.4, C9-01.6 e C9-03.1–03.4.  
**Escopo:** dois pontos pendentes; não reescrever runtimes, reabrir MCP ou implementar os aplicativos dentro do Core.

## 1. Decisão de integração

Nexus Server e Nexus Connector podem desenvolver e consumir imediatamente `get_runtime_catalog()`, `RuntimeCatalog`, `RuntimeDescriptor` e `DiscoveryRequest()`. O catálogo está entregue. O seletor pode receber do Core os tipos conhecidos, sem arrays autoritativos nos aplicativos.

Isso não equivale a uma lista de instalações prontas para binding. Falta concluir a avaliação técnica pública por candidato, já especificada em C9-01.4. O runtime também precisa preservar a operação durável em andamento quando o shutdown termina sua espera. Corrigir esse lifecycle antes de dar aceite operacional à recuperação correspondente.

Nenhum ponto deste plano permite MCP stdio, servidor/proxy/relay MCP no Core ou Connector. MCP HTTP vai diretamente do harness ao Nexus Server. O stdio dos protocolos nativos continua permitido. O Server mantém identidade canônica e autorização do agente; o Core fornece mecanismos e fatos técnicos. O transporte remoto não muda.

## 2. Evidências e limites

- Os sete testes C9 do executor e as duas sementes originais C9 passaram nesta revisão.
- Dois testes adicionais falharam: o produtor de liberação recebe cancelamento pelo timeout do shutdown; se esse cancelamento aguarda limpeza, o retorno público ultrapassa o orçamento observado. As duas falhas foram repetidas.
- O controle adicional com duas chamadas públicas de shutdown e força concorrente passou: pico de uma chamada de força ativa no cenário exercitado. Não foi transformado em novo achado.
- A ausência da avaliação pública por candidato foi verificada na API/DTO/ports e no wheel instalado. Não foi fabricado um teste que exige um nome de função arbitrário.
- Peers nativos e falhas de ledger são de laboratório. O journal e o lifecycle são reais. Estes testes não qualificam providers ou a integração de dois hosts.

Entregar o ZIP completo ao executor. `regressoes/` contém as reproduções reais; Markdown não as substitui.

## C10-00 — Baseline e preservação

### 00.1 — Registrar o estado efetivo

Registrar HEAD, branch, alterações locais, SO/Python, dependências, wheel e hash do bundle. Comparar com o snapshot pelos símbolos, não restaurar seu conteúdo. Não executar reset, nem apagar alterações posteriores.

Manter as correções já aprovadas: catálogo seguro e imutável; IDs derivados do registry; `None` como todos os descobríveis e `()` como filtro vazio; attach não qualificado; observação orçamentada; força independente; ledger com obrigação persistente rastreada.

**Aceite:** cada pendência é reproduzida no HEAD ou encerrada com prova; nenhuma mudança válida do usuário é perdida.

### 00.2 — Executar os testes recebidos antes de editar

Executar `executar_verificacao.py` e guardar XML/logs. O snapshot produz 2 falhas e 10 aprovações no conjunto de 12 casos: três desta auditoria, duas sementes C9 originais e sete C9 do repositório. Subconjuntos e repetições não são contagens adicionais da suíte completa.

Os testes mantêm o armazenamento bloqueado até depois da asserção. Não liberar a barreira antes para obter PASS; não transformar cancelamento do produtor em resultado esperado. Mudanças justificadas de fixtures são permitidas, mantendo a mesma condição causal e registrando o diff.

**Aceite:** baseline reproduzível, sem xfail/skip para esconder defeito. Erro de dependência ou plataforma deve ser separado de falha do produto.

## C10-01 — Concluir disponibilidade técnica pública para binding

**Âncoras:** `catalog.py`, `models.py:InstallationCandidate/Inventory`, `ports.py:RuntimeCore`, `runtime.py:discover`, `discovery.py`, políticas de qualificação em `native/adapters/compatibility.py`, `native/process/preflight.py`, `inventory_reducer.py`, `docs/api.md`.

### 01.1 — Publicar uma avaliação por candidato, sem expor internals

Adicionar DTO e entrada pública documentados para avaliar as instalações encontradas. Pode ser uma função independente ou método do port. O nome não é obrigatório; o comportamento é. A mudança deve ser aditiva sempre que possível.

O consumidor não deve precisar importar `native.adapters.compatibility` ou reconstruir suas regras. Reutilizar internamente a qualificação e o preflight existentes. Catálogo permanece uma consulta barata de metadados e não passa a executar discovery/probes implicitamente.

O resultado deve separar, conforme evidência disponível:

| Dimensão | Informação mínima |
|---|---|
| Referência | adapter_id e referência opaca do candidato, sem colapsar versões |
| Observação | versão, arquitetura/build e revisão/identidade da evidência pertinente |
| Presença/confiança | encontrado, selecionado/trusted, ou ainda requer seleção |
| Plataforma | compatível com implementação e host de execução, não o host que renderiza a UI |
| Qualificação | comprovada, não qualificada ou não observada |
| Contenção | disponível, indisponível ou não verificada |
| Preparação | pendências técnicas de configuração, sem revelar secrets |
| Resultado | estado técnico e razões estáveis; capacidades apenas quando comprovadas |

Nomes sugeridos de estados: `NOT_INSTALLED`, `UNSUPPORTED_PLATFORM`, `NOT_PROBED`, `UNQUALIFIED_BUILD`, `CONTAINMENT_UNAVAILABLE`, `PREPARATION_REQUIRED`, `READY_FOR_RUNTIME`. Não é exigido adotar exatamente esses nomes; a distinção é obrigatória. `READY_FOR_RUNTIME` nunca significa autorização do agente.

**Aceite:** consumidor instalado consegue obter avaliação por candidato sem imports privados, abrir sessão ou registrar um agente. Dados insuficientes resultam em estado inconclusivo, nunca READY por omissão.

### 01.2 — Aplicar a mesma política usada na execução

Derivar a avaliação dos mecanismos reais de suporte/qualificação do Core. Não criar outra allowlist para o catálogo e não duplicar `qualified_build` nos aplicativos. Avaliação passiva não faz login de provider nem spawn para tentar inferir disponibilidade. Qualquer probe ativo exige opção/autorização explícita e as mesmas proteções já existentes.

Distinguir o máximo declarado pelo adaptador das capacidades efetivas do build/configuração. `managed_supported`, `discoverable=True` ou presença de `darwin` no descritor não comprovam contenção disponível. `claude_attach` permanece indisponível até qualificação própria.

Erros recuperáveis de uma família devem ser expressos naquela entrada, sem descartar silenciosamente todo o inventário. IDs explicitamente desconhecidos e erros globais de autorização continuam tipados. O discovery de todos deve considerar os adaptadores pertinentes ao host; não iniciar attach sem alvo/escopo.

**Aceite:** binário presente, build desconhecido, plataforma incompatível e contenção ausente não aparecem como tecnicamente prontos. Prepare/open continuam revalidando para detectar drift posterior.

### 01.3 — Projetar os resultados sem vazar dados locais

Preservar `InstallationCandidate` para uso interno/local, mas publicar uma projeção remota segura. Não enviar `asdict(InstallationCandidate)` indiscriminadamente: há caminhos de executável e script. Reutilizar os IDs opacos existentes do inventário quando adequado ou documentar quem atribui/resolve a referência; não é necessário criar outra identidade de agente.

Uma mesma família pode produzir dois candidatos/versões e estados distintos. O binding deve referenciar executor + adapter + candidato/revisão. Não escolher por display_name nem inferir que diretórios idênticos em hosts diferentes equivalem ao mesmo recurso.

Se os novos dados forem transmitidos em frames NXL, ajustar schemas e negociação de revisão deliberadamente e atualizar fixtures/consumers. Não acrescentar campos a frames com `additionalProperties=False` sem atualizar o contrato. Também é válido projetar por API do aplicativo explicitamente versionada, sem implementar HTTP dentro do Core. Escolher uma opção e documentar os dois consumidores.

**Aceite:** projeção serializável, sem classes/módulos carregáveis, credenciais ou caminhos desnecessários. Sem imports arbitrários a partir do catálogo recebido.

### 01.4 — Entregar o contrato de consumo aos aplicativos

Documentar os dois caminhos:

- Local: Core embutido no Server produz catálogo e avaliação; Server aplica políticas e publica opções à UI.
- Remoto: Core do Connector produz os fatos do seu host; Connector envia projeção; Server aplica políticas e apresenta as opções daquele executor.

A UI mantém apenas apresentação/filtros e não uma enumeração autoritativa de runtimes. `OFFLINE`, `STALE`, TTL, conexão e autorização pertencem aos hosts; não ao catálogo estático. Catálogo e disponibilidade em cache são projeções versionadas, não uma nova lista editável.

Fornecer exemplo executável contra o wheel usando API pública, incluindo duas instalações da mesma família, attach não disponível e ausência de probe. Testes de UI real pertencem ao repositório Server: entregar fixture e critério, não alegar que o Core os executou.

**Aceite:** para adicionar um tipo conhecido, não editar arrays de runtimes nos dois aplicativos. Para avaliar um candidato, não copiar regras de build/plataforma/containment.

## C10-02 — Separar produtor durável da espera cancelável do shutdown

**Âncoras:** `runtime.py:shutdown` (≈1182–1206), `_schedule_release_retries` (≈1907–1960), `_retry_release_obligations`, `_ReleaseObligation`, `_contain_late_open`; contrato `OwnedSlotLedger` e journal off-loop.

### 02.1 — Identificar os proprietários e corrigir a coleção de tarefas

Hoje `obligation.retry_task` é colocado em `_cleanup_tasks`. O shutdown usa `wait_for(gather(*_cleanup_tasks), ...)`. Quando o prazo vence, esse gather cancela exatamente o produtor que deveria continuar possuído. Proteger apenas o collector por `shield` não protege o produtor em outro gather.

Manter produtor e token no registro de obrigação ou em coleção proprietária separada. Ele não pode participar desprotegido de um gather cancelado pelo orçamento do cliente. Separar ao menos: produtor durável, coletor/finalizador e waiter público. Cancelar a última camada não descarta as duas primeiras.

**Aceite:** `test_shutdown_deadline_does_not_cancel_owned_release_producer` passa e comprova que o produtor não recebeu CancelledError apenas porque o orçamento de resposta terminou. Registro, chave e possibilidade de confirmação continuam disponíveis.

### 02.2 — Dar orçamento à espera, não ao commit

O retorno público precisa ter orçamento total documentado, incluindo recuperação. Use espera não destrutiva por produtores possuídos (`asyncio.wait` com timeout ou composição equivalente com shield e referência forte). Não aguardar a conclusão do cancelamento de uma unidade durável para poder retornar.

Se o backend demora a encerrar sua própria operação, preservar a supervisão e retornar pendência. Não prometer rollback, sucesso, commit ou morte de processo por timeout. Não aumentar artificialmente o orçamento até os testes deixarem de observar a espera.

Revisar os dois gathers de cleanup do shutdown, cancelamento externo do chamador e chamadas concorrentes. Não trocar indiscriminadamente todo gather do projeto: distinguir operações possuídas de tarefas efêmeras.

**Aceite:** `test_shutdown_return_does_not_wait_for_release_cancel_cleanup` retorna dentro do envelope enquanto a barreira continua fechada. O orçamento de laboratório é generoso frente a `(0,0)` e cleanup de 0,03 s; não é um SLO universal.

### 02.3 — Coalescer e colher o resultado antes de agendar novamente

Todas as rotas da mesma reserva devem consultar a obrigação antes de fazer release: liberação inicial de handle parado, retomada e shutdown. Não iniciar outro produtor apenas porque outro waiter terminou. Se `retry_task` terminou, consumir primeiro seu resultado; não substituí-lo por outra liberação antes de processar um sucesso já disponível.

Para a mesma chave/owner:

| Estado | Ação |
|---|---|
| Sem produtor e obrigação pendente | Criar um produtor e registrar token |
| Produtor em voo | Compartilhar resultado; não duplicar |
| Sucesso confirmado | Finalizar a obrigação exata |
| Falha comprovadamente pré-entrega | Manter pendência retryable, sem alterar o recurso físico |
| Confirmação perdida/resultado incerto | Consultar/idempotência conforme port; não apagar nem supor rollback |
| Waiter cancelado | Mudar só a espera; preservar produtor e finalizador |

Não basta segurar a coroutine se ela própria abandona uma thread: o contrato do port precisa conservar a unidade que ainda pode comitar. Reaproveitar a implementação off-loop e sua evidência de resultado.

**Aceite:** duas chamadas de shutdown não sobrepõem releases equivalentes; conclusão que chega depois do primeiro retorno é aplicada uma vez, sem reset de tentativa nova.

### 02.4 — Convergir pelo lifecycle público, com relatório honesto

Ao restaurar storage, concluir a mesma liberação, limpar somente a obrigação confirmada e conservar histórico/recibos. Não exigir acesso a `_owned_slots` ou flags privadas pelo consumidor. O relatório deve distinguir pendência apenas durável de processo ainda incerto; não omitir a sessão como se estivesse tudo concluído.

Disposal de pools físicos depende dos recursos físicos; o mecanismo/registro necessário ao commit continua alcançável. Um ledger preso de recurso parado não atrasa contenção de outro recurso vivo. Não reabrir harness nem disparar força para tentar descobrir o estado do banco.

**Aceite:** sementes originais Y01/Y02 e controles C8 permanecem verdes; storage restaurado libera a mesma reserva; nenhuma execução nativa adicional em consequência de release pendente.

### 02.5 — Provar cancelamento, recuperação e independência

Executar os dois testes novos duas vezes, além do controle de força e das sementes C9. Acrescentar casos de cancelamento externo do chamador, duas chamadas públicas concorrentes, sucesso tardio antes da chamada seguinte, erro depois de commit, recusa anterior e outro handle precisando de força.

Contar calls no backend quando alegar coalescência física. Não inferir ausência de efeito de `Task.cancelled()` nem usar comparação textual de código como prova. O peer sintético não qualifica um provider real.

**Aceite:** evidências demonstram prazo do waiter, sobrevivência do produtor, chave da liberação, resultado durável e ausência de novo spawn. Falhas externas recebem estados próprios, não PASS automático.

## C10-03 — Integração e encerramento

### 03.1 — Artefato único e compatibilidade

Gerar wheel/sdist; instalar fora da árvore; testar import público, catálogo, disponibilidade, consumo local/sintético remoto e bundle com hash fixado. Manter geração dos schemas a partir do registry. Campos novos são aditivos ou versionados; não rotacionar IDs nem apagar estado incerto para migrar.

Publicar o contrato aos dois agentes com pin exato do wheel e revisão. Eles não contornam o Core copiando adaptações de runtimes ou qualificação.

### 03.2 — Evidência e declaração proporcional

Separar teste do código, backend real do SO, provider real e integração dos aplicativos. Os XMLs recebidos do executor não equivalem a uma execução do revisor. Corrigir datas de campanha que divergem dos timestamps dos próprios XMLs; no pacote atual a narrativa C9 usa 30/09/2026 enquanto os XMLs completos registram 28/09/2026. Esse ajuste documental não é um terceiro bloqueador.

C10 se encerra com disponibilidade consumível sem duplicação de regras e producer de release preservado sob timeout/cancelamento. Desenvolvimento dos aplicativos pode continuar antes disso; aceite operacional desses caminhos depende da correção e da evidência pertinente. Não declarar E2 a partir dos exemplos sintéticos e não habilitar attach por constar no catálogo.

**Entregáveis:** diff/commits; testes e comandos; XMLs e hashes; matriz de estados; mudanças públicas; decisões de compatibilidade; limitações de suporte. Nenhuma autorização de publicação, push, alteração de permissões ou uso de credenciais reais é concedida por este documento.
