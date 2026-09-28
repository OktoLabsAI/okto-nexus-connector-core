# Validação do Core 0.2.7.dev0 e prontidão dos consumidores

## Conclusão

**Sim: iniciar/continuar agora o desenvolvimento do Connector e a integração com o Nexus, em paralelo e com versão fixada. Não considero necessário concluir todo o Core antes de desenvolver os aplicativos.**

Isso não equivale a liberar operacionalmente o runtime. Identifiquei duas falhas de recuperação confirmadas e uma lacuna de contrato importante para a integração solicitada:

- **C01 — catálogo público ausente:** os runtimes estão centralizados na implementação, mas a enumeração suportada para consumidores não está publicada. É o primeiro contrato a entregar para evitar listas duplicadas na UI/Server/Connector.
- **Y01 — P1:** retry de uma força já concluída com erro fica dependente de uma nova observação que pode bloquear. Afeta contenção na recuperação de handles tardios.
- **Y02 — P2:** a tentativa de liberar uma reserva persistida pode bloquear o retorno de shutdown sem orçamento, depois de o processo já ter sido observado como parado.

Não encontrei motivo para reescrever os adaptadores, alterar a identidade centrada no agente, mudar o transporte aprovado ou reintroduzir MCP no Connector/Core. Os achados C8 específicos passaram na nova versão.

## Snapshot e método

ZIP `okto-nexus-connector-core-main(6).zip`, comentário Git `6a43e90a787f3a87af8e26f3f93d4c708cf8a0a8`, pacote `0.2.7.dev0`. Comparação com ZIP anterior `9f0ebab...` e com o plano C8. Inspeção de fonte, tipos/exportações, catálogo interno, discovery, gerador NXL, docs e evidências. Execução das sementes originais C8/C7, testes reconstruídos C8, regressões históricas, suíte completa e duas novas reproduções. Build por setuptools e instalação fora da árvore.

**390 arquivos originais foram comparados com o ZIP por hash e permaneceram inalterados.** Código extra de teste e artefatos estão fora da árvore original.

Os consumidores Server e Connector reais não foram analisados ou executados nesta rodada. As orientações de integração abaixo são o contrato recomendado a implementar, não afirmação de que já existem endpoints ou telas nos aplicativos.

## 1. Centralização dos runtimes: correta na implementação, incompleta no contrato público

### 1.1 O que já existe

`src/nexus_connector_core/native/registry.py` contém `_SPECS`, `adapter_specs`, `adapter_spec` e o carregamento lazy das classes. Há quatro entradas:

| adapter_id | Família | Modo |
|---|---|---|
| codex_app_server | Codex | gerenciado |
| pi_rpc | Pi | gerenciado |
| claude_stream | Claude Code | gerenciado |
| claude_attach | Claude Code | attach, não qualificado |

O código dos adaptadores e seus backends está dentro do Core. `discovery.py` já deriva `EXECUTABLE_NAMES` de `adapter_specs()`, exemplo correto de reutilização da fonte única. Não encontrei dependência de execução importando o checkout do Server/Connector.

A existência da entrada attach não significa capacidade operacional: a documentação e a qualificação a mantêm indisponível. Plataformas na tabela representam cobertura de implementação, não prova de que contenção e provider foram qualificados em cada plataforma.

### 1.2 O que falta

A documentação `docs/api.md:3–7` diz que os módulos de adaptadores nativos não são API pública dos hosts. O pacote e o `RuntimeCore` não exportam método de catálogo/descritivo de runtimes. `DiscoveryRequest(adapter_ids)` exige uma tupla de IDs e `runtime.discover` só percorre a lista recebida; `Inventory` devolve candidatos, não um catálogo de famílias conhecidas/ausentes com razões de indisponibilidade.

Tecnicamente é possível importar `native.registry.adapter_specs`. **Isso não atende ao contrato de consumo estável definido pelo próprio projeto.** Recomendar esse import como solução para os aplicativos preservaria o acoplamento à estrutura interna que tentamos remover.

A observação pelo wheel instalado está em `evidencias/catalogue_observation.json`: não há export de catálogo, o request exige IDs e o registry interno contém as quatro entradas. Essa observação usa import interno apenas para auditoria; não é exemplo de produção.

Há também uma lista manual repetida em `contracts/generate.py:86–87` e `101–102` para os enums de candidato e capacidade. Os valores coincidem hoje; **não há disparidade atual demonstrada**, mas são fontes editadas separadamente. O gerador deve derivá-los da fonte única, preservando regras de versionamento dos contratos publicados. JSON gerado pode repetir valores sem ser outra fonte autoritativa.

### 1.3 O contrato desejado

Três conceitos separados:

1. **Catálogo:** quais adaptadores esta versão do Core conhece e quais são seus metadados públicos. Consulta barata, sem processo, credencial, journal ou agente.
2. **Disponibilidade local:** quais candidatos estão instalados, confiáveis, compatíveis e qualificados no executor; quais requisitos faltam. Produzida no host dos harnesses, não pelo SO do Server remoto.
3. **Elegibilidade do binding:** disponibilidade somada às permissões e políticas do agente aplicadas pelo Nexus Server. O Core não passa a autorizar identidades canônicas.

A UI do Nexus deve receber opções da API do Server referentes ao executor escolhido. Se for local, o Server consulta o Core embutido. Se for remoto, consome inventário/catálogo produzido pelo Core do Connector autenticado. Não manter array de Codex/Pi/Claude na UI nem usar as instalações do Server para preencher opções de outro host.

Um consumidor pode filtrar, agrupar ou traduzir labels, mas não declarar outra lista de tipos suportados. A seleção identifica executor, adapter e candidato/revisão; múltiplas versões locais não são uma única opção indistinta. Desconexão/cache vencido deve impedir tratar inventário antigo como disponibilidade atual.

A primeira entrega deve ser API pública aditiva com DTO sem módulo/classe/caminho sensível, descoberta sem lista manual e avaliação de prontidão reutilizando a qualificação existente. Não é necessário implementar plugins dinâmicos, novo protocolo ou servidor HTTP no Core.

## 2. Y01 — Retentativa de força bloqueada pela observação

**Prioridade P1; não impede desenvolver os aplicativos, mas impede ratificar a garantia de contenção operacional no caminho afetado.**

Âncora: `runtime.py:1771–1806`. A primeira força é paralela; para repetir uma força anterior concluída, o fluxo chama `await native.observe()` antes de decidir o retry. Se o observer não responde, nenhuma nova força é solicitada.

Reprodução `test_y01_force_retry_is_not_gated_by_stalled_observer`:

- abertura cancelada devolve um native de laboratório;
- primeira força termina com erro temporário; primeira observação confirma RUNNING;
- registro e handle continuam retidos;
- antes do próximo shutdown público, bloqueia-se a observação;
- shutdown retorna, mas a segunda força não é alcançada enquanto o observer fica retido.

Observação: `force_calls=1`, `observer_blocked=True`, `same_resource_retained=True`, `shutdown_returned=True`. A primeira força já havia terminado: não se trata de pedir duplicação de uma chamada em voo. As sementes de coalescência X03 passaram e devem continuar passando.

A prova usa Core/journal reais e peer nativo controlado, não provider real. Não afirma que o SO sempre conseguirá matar o processo; exige que a rota de contenção chegue ao backend independentemente da consulta que falhou.

Correção: conservar último resultado físico e última observação; separar unidade de observe da decisão de retry de força; não iniciar nova força se STOPPED já estiver comprovado; enquanto ownership válido e parada desconhecida, não deixar observe impedir controle por tempo indefinido. Reutilizar o coordenador existente, com produtores e quotas; não criar terceira implementação de cleanup.

## 3. Y02 — Liberação durável pendente pode prender o shutdown

**Prioridade P2, erro de lifecycle/limites.**

Âncoras: `runtime.py:1168–1171` e `1841–1856`. `shutdown` chama diretamente `_retry_release_obligations()`. Essa rotina espera `release_owned_slot()` sem limite. O retorno público e a recuperação dos demais handles tardios ficam depois dessa espera.

Reprodução `test_y02_shutdown_budget_covers_stopped_release_obligation`:

- handle tardio chega a STOPPED;
- primeira liberação da reserva falha antes de commit, criando obrigação corretamente;
- próxima liberação fica bloqueada por evento, sem ser liberada antes da assert;
- shutdown `(0,0)` com cleanup 0,03 s continua pendente depois de 3 s.

Observação: `returned=False`, `ledger_still_blocked=True`, `obligation_retained=True`, `physical_stop=True`. Não é perda da obrigação — esse ponto do C8 foi corrigido. É espera pública sem limite na recuperação.

Correção: produtor de release possuído, orçamento de espera e resposta com pendência identificada; retomada idempotente e coalescida quando storage voltar. Não abandonar o commit em curso ao cancelar o waiter. Não impedir força de outro recurso porque um processo já parado tem pendência de banco. Não relançar o harness para recuperar quota.

## 4. Campanhas executadas

| Campanha | Resultado |
|---|---|
| C8 original + C8 entregue | 10 PASS (5 + 5) |
| C7 original | 9 PASS |
| Histórico C2–C7 entregue | 70 PASS, 1 SKIP |
| Novos testes Y01/Y02 | 2 FAIL |
| Repetição final Y01/Y02 | 2 FAIL |
| Suíte completa final | 704 PASS, 123 FAIL, 20 SKIP |
| Build wheel/sdist | PASS |
| Instalação isolada e consumers embedded/remote | PASS |
| Conformance do bundle | PASS com opt-in explícito development-partial |

Subconjuntos, cópias de sementes e repetições não se somam à suíte completa. As 123 falhas finais estão listadas em `evidencias/full_failures.json`: concentram-se na indisponibilidade de `proc_children` neste ambiente e nas consequências de não comprovar parada, como retenção conservadora de slots. Não são 123 bugs independentes; não houve remoção do gate de contenção. Y01/Y02 foram executados separadamente e não dependem dessas falhas de plataforma.

Houve warnings e logs de exceção de tarefa nos testes de falha injetada; os logs completos estão preservados. Não declaro campanha sem warnings. A primeira execução completa foi interrompida e preservada como preliminar porque a dependência estava apenas no PYTHONPATH; a campanha final ocorreu após validar import em subprocesso isolado.

O acesso pip à rede estava indisponível. `rfc8785==0.1.4` foi recuperado da fonte oficial via GitHub, disponibilizado localmente e comparado por Git blob SHA com a versão oficial. Não foi usado stub de canonicalização. A proveniência e o teste `python -I` estão no pacote. Build via `setuptools.build_meta`; os hashes são dos artefatos desta auditoria, sem alegação de igualdade byte a byte com o build normalizado do executor.

O wheel foi instalado fora da árvore; as duas formas sintéticas de consumo usaram o mesmo artefato. Não houve execução de provider real, campanha Windows/WSL2 ou integração dos produtos em dois hosts. As campanhas entregues pelo executor são evidência recebida, não reproduzida aqui. Seu documento C8 apresenta datas 29/30 de setembro de 2026, posteriores à data desta sessão (28/09/2026); essa proveniência temporal requer conferência antes de uso como registro de release, sem que isso por si só prove defeito funcional.

## 5. Recomendação prática para os três repositórios

**Core:** publicar catálogo/DTO de disponibilidade primeiro; corrigir Y01/Y02 paralelamente; entregar versão exata do wheel e revisão dos contratos.

**Connector:** iniciar daemon/CLI/identidades/bindings/canal remoto; usar o catálogo do Core para opções e o próprio host para discovery. Não criar lista própria nem servidor MCP.

**Nexus Server:** iniciar composição com Core, API de projeção local/remota, permissões e seletor genérico. O runtime local não exige instalar a aplicação Connector. A UI deve ser orientada pelo catálogo do executor escolhido.

**Integração operacional:** usar o mesmo wheel corrigido nos dois consumidores e qualificar primeiro um adaptador ponta a ponta, local e remoto. Depois ampliar. Uma API pública ausente pode ser construída logo no primeiro incremento; não justifica deixar todo o desenvolvimento dos aplicativos parado, nem copiar temporariamente a lista interna para produção.

O plano C9 está em `02_PLANO_C9_CATALOGO_E_RECUPERACAO.md`; as duas regressões executáveis e os testes anteriores estão no ZIP. Nenhuma correção foi aplicada ao produto nesta auditoria.
