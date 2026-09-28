# Plano C11 — identidade inequívoca da instalação no seletor

**Baseline revisado:** `6909435ff0d913cda03494f26bda670e2d3e75b0`, `0.2.9.dev0`.
**Destinatário:** agente executor do Core. **Escopo:** apenas A11-01, P2, com continuidade das correções C10.

## Decisão e fronteira

Não reescrever a biblioteca nem interromper o trabalho independente do Server/Connector. O catálogo de tipos e a avaliação de qualificação/plataforma/containment estão disponíveis. O único achado novo comprovado é a impossibilidade de distinguir cópias iguais em locais diferentes pelo `candidate_ref` da projeção.

A implementação atual usa `candidate.fingerprint`; para Codex/Claude ele é hash dos bytes. Isso representa conteúdo, não instalação. Manter duas linhas idênticas não fornece informação para escolher uma delas. Na API local, caminhos diferentes continuam presentes; o problema aparece na projeção selecionável. Não foi observado um aplicativo executando o alvo errado.

## Invariantes preservadas

MCP HTTP direto apenas no Nexus Server. Core e Connector não oferecem MCP stdio/HTTP, fachada ou proxy. Stdio nativo dos harnesses permanece permitido. Identidade canônica é do agente; instalação/candidato não é agente nem usuário. Qualificação, conteúdo e autorização são diferentes. `READY_FOR_RUNTIME` nunca concede binding. A lista autoritativa de adaptadores permanece única no Core. Cancelamento público não abandona produtor durável; preservar as correções verificadas do C10.

## Arquitetura sugerida, sem impor nomes

`adapter_id` identifica o mecanismo; `build_identity` identifica bytes/layout qualificados; `installation_ref` ou `candidate_ref` identifica uma instalação local selecionável; `inventory_revision` identifica a evidência; `executor_id` delimita o host. A UI recebe os campos necessários, mas os alvos físicos permanecem locais.

Preferir alteração aditiva pequena. Uma referência opaca derivada no Core de alvos normalizados com domínio/versionamento é suficiente se o host valida revisão e escopo. ID persistido localmente também é válido quando necessário à política de estabilidade. Não criar serviço de registro global nem cadastro de usuário. Hash de caminho não é criptografia: se a política exigir não correlacionar caminhos entre hosts, o host deve fornecer escopo/salt persistente por port explícito. Não elevar essa opção de privacidade a requisito desnecessário para fechar a unicidade.

Exemplo de integração desejada (nomes ilustrativos, não API já existente):

```python
catalog = get_runtime_catalog()
inventory = await runtime.discover(DiscoveryRequest())
report = evaluate_runtime_availability(inventory)
# Host anexa executor_id/revision e apresenta a projeção à UI.
# A seleção volta ao MESMO host e à revisão autorizada.
selected = resolve_installation(inventory, adapter_id, candidate_ref)
# Compor/selecionar pelo mecanismo público existente e preparar esse candidato.
```

O helper deve ser público ou a regra de mapeamento deve ser produzida publicamente pelo Core. Não exigir `native.registry`, `CopiedAdapterFactory` nem réplica do algoritmo nos aplicativos. A revisão e a autorização continuam no host; o Core não cria endpoints de rede.

## Plano de execução

## C11-00 — Baseline e contrato da identidade

Dependências: nenhuma.

### C11-00.01 — Reproduzir sem mudar a seleção

**Implementar:** Registrar HEAD real, versão, dirty state e hashes. Rodar os testes novos com duas cópias byte-idênticas descobertas de fato. Conservar os caminhos locais distintos e os hashes de build iguais. Registrar as duas linhas da projeção sem expor diretórios privados.

**Não resolver assim:** Não corrigir a fixture atribuindo manualmente fingerprints diferentes. Não descartar a segunda instalação.

**Aceite:** Os dois FAIL pertencem ao campo de identidade, não à ausência de contenção, provider ou probe.

### C11-00.02 — Definir instalação versus conteúdo

**Implementar:** Documentar quatro identidades: adapter_id, build_identity/fingerprint, instalação selecionável e agente. Estabelecer se symlinks que resolvem para o mesmo alvo são aliases da mesma instalação. Definir estabilidade para mesma instalação em nova enumeração e semântica após update/movimentação.

**Não resolver assim:** Não transformar o hash de build em hash de path para forçar unicidade. Não declarar instalações distintas equivalentes somente porque os bytes coincidem.

**Aceite:** Existe uma decisão explícita para mesmo alvo, mesmo conteúdo em dois alvos, rename, mudança de conteúdo e dois hosts.

## C11-01 — Referência local opaca e resolução única

Dependências: C11-00.

### C11-01.01 — Implementar identidade de instalação no Core

**Implementar:** Adicionar uma fonte de referência da instalação no fluxo de discovery/avaliação, sem duplicar a lista de adaptadores. Recomendação: identidade derivada ou registrada localmente a partir de adapter_id e alvos canônicos (executable e launch_script quando presente), com domínio/versão do algoritmo. A instalação deve receber referência diferente se o alvo físico selecionável for diferente. Uma alternativa válida é ID opaco atribuído pelo inventário do host com port público e armazenamento local consistente; o Core valida unicidade e produz a projeção. Escolher uma implementação, não duas autoridades.

**Não resolver assim:** Não usar índice do array, random a cada chamada, nome de exibição, ID do agente ou versão textual como identidade. Não reescrever fingerprints/allowlists existentes.

**Aceite:** Cópias iguais em A/B têm refs distintas; o mesmo inventário repetido mantém refs; referência não contém caminhos literais.

### C11-01.02 — Resolver uma seleção de forma pública e inequívoca

**Implementar:** Expor helper/port público de lookup, ou especificar e testar um mapeamento público único do inventário produtor. O input é adapter_id + candidate_ref associado à revisão correta; o resultado local é exatamente um InstallationCandidate, mantendo paths no host. Zero resultados produz erro tipado de referência ausente/desatualizada. Mais de um resultado produz erro tipado de ambiguidade, nunca escolha automática. Documentar como o host passa o candidato resolvido à composição/prepare existente, sem importar native.*.

**Não resolver assim:** Não criar endpoint HTTP/MCP no Core. Não escolher candidates[0] nem exigir que cada aplicativo recalcule hashes de paths.

**Aceite:** Selecionar A resolve A; selecionar B resolve B, inclusive após reordenar o inventário. Nenhum runtime é iniciado para resolver.

### C11-01.03 — Distinguir referência estável e prova de revisão

**Implementar:** Manter os fingerprints/conteúdo separados da referência. Se a referência for estável por caminho, um update deve invalidar a evidência/revisão antiga e prepare/open deve continuar recusando drift. Se a referência mudar no update, o ID anterior deve ser tratado como stale. Executor e revisão pertencem ao envelope do host, e precisam acompanhar a seleção; a referência não concede autorização nem substitui a prova do alvo.

**Não resolver assim:** Não supor que conhecer a ref autoriza abrir. Não importar automaticamente caminhos de outro executor ou usar equivalência textual de diretórios para compartilhar binding.

**Aceite:** Teste de mudança entre listar e preparar não abre conteúdo novo por aprovação antiga; ref de outro executor não resolve no inventário local correspondente.

### C11-01.04 — Fechar a projeção e metadados

**Implementar:** CandidateAvailability deve identificar cada instalação presente e manter estado/razões calculados pelas políticas existentes. A linha NOT_INSTALLED é informativa, não selecionável; não necessita receber identidade de instalação fictícia. Aplicar unicidade por adapter_id/ref para candidatos presentes. Fornecer rótulo de apresentação local/aprovado quando necessário para o humano diferenciar cópias, sem expor path completo automaticamente. Não usar esse rótulo como chave.

**Não resolver assim:** Não remover linhas legítimas nem fundir duas instalações para eliminar a colisão. Não ampliar READY ou desativar preflight para obter igualdade nos testes.

**Aceite:** Duas opções podem ter o mesmo display_name e build, mas sua seleção é inequívoca. UNKNOWN/NOT_PROBED e attach continuam restritivos.

## C11-02 — Versionamento e contrato dos consumidores

Dependências: C11-01.

### C11-02.01 — Versionar a mudança sem remapear bindings antigos

**Implementar:** A semântica de candidate_ref muda; incrementar a versão da projeção ou introduzir campo inequívoco aditivo com migração documentada. Não redefinir silenciosamente o significado da versão 1 já entregue. Uma referência antiga baseada só no fingerprint pode migrar automaticamente apenas quando o inventário do mesmo executor comprovar exatamente um alvo; caso contrário exigir reseleção explícita. Preservar agentes, chaves, histórico e operações duráveis.

**Não resolver assim:** Não rotacionar chave de agente, reabrir sessões ou substituir binário por ordem para resolver referência legada.

**Aceite:** Teste v1 com dois alvos recusa migração ambígua; v1 único tem caminho documentado. Catálogo de tipos pode manter sua versão se sua forma/semântica não mudar.

### C11-02.02 — Entregar exemplos local e remoto

**Implementar:** Atualizar examples/availability_projection.py e docs/api.md. Exemplo precisa conter duas instalações com mesmos bytes, não apenas duas strings diferentes inventadas de fingerprint. Mostrar catálogo -> discovery -> avaliação -> projeção -> seleção -> resolução local -> prepare existente. Server usa Core local; Connector usa Core remoto e o Server apresenta esse snapshot. Declarar onde executor_id/inventory_revision/TTL são validados. Não implementar aplicativos dentro do Core.

**Não resolver assim:** Não afirmar teste da UI real nem E2 por executar exemplo. Não exigir arrays autoritativos de adapters em Server/Connector.

**Aceite:** O mesmo contrato e helper público atendem ambos os hosts, sem nomes de classes/módulos nativos na projeção.

### C11-02.03 — Fixar contratos e migração na negociação

**Implementar:** Se a projeção permanecer na API versionada dos aplicativos, documentar seu número de formato e versões aceitas por cada consumidor. Se entrar em NXL, alterar schemas/revisão explicitamente e executar conformance; não inserir campos em frames que proíbem propriedades extras. Desconhecer versão deve tornar seleção indisponível/incompatível, não carregar classes arbitrárias.

**Não resolver assim:** Não mudar NXL apenas para uma refatoração interna sem necessidade; não ignorar negociação para renderizar como READY um candidato de formato desconhecido.

**Aceite:** Consumidor instalado serializa a projeção revisada, reconhece compatibilidade e não depende da árvore de fonte.

## C11-03 — Aceite e liberação delimitada

Dependências: C11-01, C11-02.

### C11-03.01 — Testar causa e controles

**Implementar:** Executar duas vezes as duas regressões de colisão e os três controles do pacote. Acrescentar resolução A/B, reordenação, drift, migração legada e escopo. Isolar preflight somente nos testes unitários de composição de estados quando necessário; manter campanha real de contenção separada e o código fail-closed inalterado.

**Não resolver assim:** Não marcar PASS por mudar expected para refs iguais; não remover arquivos duplicados da fixture nem reduzir o teste a IDs arbitrários diferentes.

**Aceite:** Todos os testes de identidade passam pela API pública e pelo wheel; três controles continuam válidos.

### C11-03.02 — Preservar recuperação e produzir artefato

**Implementar:** Rodar sementes C10/C9 completas, histórico e suíte no ambiente efetivamente disponível. Construir wheel/sdist em cópia; instalar fora da árvore; rodar catálogo, disponibilidade e consumers. Registrar comandos, XMLs, hashes, erros ambientais e não executados. Os testes C10 de unit readiness podem usar preflight positivo controlado, sem apresentá-lo como qualificação real.

**Não resolver assim:** Não voltar aos gathers canceláveis para tratar obrigações de release. Não somar repetições/subconjuntos como cobertura nova nem usar o total bruto de falhas do sandbox como diagnóstico independente.

**Aceite:** Nenhuma regressão de cancelamento durável; mesma fonte de tipos; artefato exato publicável aos dois consumidores sem acesso privado.

### C11-03.03 — Declarar conclusão proporcional

**Implementar:** Entregar diff, commit, formatos, regra de identidade, caminho de resolução, migração e evidência por cenário. A11-01 fecha com seleção local inequívoca e representação remota suficiente. Há autorização técnica para avançar integração em paralelo, não para publicar release ou operar providers com credenciais reais. Qualificação operacional e UI permanecem por ambiente/consumidor.

**Não resolver assim:** Não inventar novos subsistemas ou novas rodadas por estilo. Se os comportamentos necessários passaram, encerrar este ajuste.

**Aceite:** Relatório distingue correção de contrato, execução unitária, backend real, provider real e integração de dois hosts.

## Entrega e uso do pacote

Rodar `executar_verificacao.py` antes e depois. As duas falhas novas são expectativas corretas; os três controles impedem que a solução destrua estabilidade, separação de build ou privacidade. As sementes originais C10/C9 acompanham o pacote para preservar a correção de shutdown. Não enviar apenas Markdown ao executor.

O agente deve implementar as tarefas, não escrever outro plano em lugar da correção. Preserve alterações posteriores ao baseline; não faça reset. O pacote não concede autorização de push, release público, rotação de credenciais, alteração de autorização ou chamada de providers pagos.

Critério de encerramento: o host consegue identificar e resolver exatamente a instalação selecionada, mesmo com duas cópias byte-idênticas e ordem de inventário alterada; evidencia/revisão continua recusando drift; metadados não expõem paths; ninguém copia a lista de runtimes. Sem novos erros comprovados, este ajuste está encerrado.
