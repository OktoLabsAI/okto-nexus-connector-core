# Entregar ao agente responsável pelo okto-nexus-connector-core

## Como usar

Copie esta pasta para o repositório do Core, por exemplo `plans/correction-c1/`, preservando o plano R3 e as evidências existentes. Abra uma instância do Codex nesse repositório e envie o prompt abaixo. O snapshot-base é `706b16a90c54a654551519cdc357bd6fedb9427e`; o agente deve reconciliar o HEAD, nunca resetá-lo para esse commit.

O escopo é implementação de correções no Core. Outros repositórios continuam independentes e recebem `03_HANDOFF_SERVER_CONNECTOR.md`. O pacote fornece 100 tarefas em 15 fases e 129 cenários, todos inicialmente não concluídos/não executados.

## Prompt pronto para copiar

```text
Você é o agente responsável pela correção do repositório okto-nexus-connector-core.
Trabalhe sobre a implementação existente; não faça reescrita integral nem crie Core paralelo.

Leia integralmente o pacote de correção C1:
- 01_PLANO_CORRECAO_CORE.md
- 02_MATRIZ_REGRESSOES.md
- 03_HANDOFF_SERVER_CONNECTOR.md
- 04_GATES_E_EVIDENCIAS.md
- BACKLOG_CORRECAO.json
- referencias/RELATORIO_AUDITORIA_CORE.md
- referencias/03_PLANO_NEXUS_CONNECTOR_CORE_R3.md

Primeiro execute PC00: registre HEAD/status/versão/ambiente, compare o snapshot
706b16a90c54a654551519cdc357bd6fedb9427e e classifique F01–F07/G01–G06 no código
atual. Preserve alterações posteriores e não faça reset ou remoção de estado.

Implemente as fases de acordo com as dependências. Priorize journal off-loop,
contenção independente de send/storage, guarda na fronteira real do efeito,
EOF, IDs com consulta legada e composição pública. Não pare na elaboração de
outro plano: entregue código, testes e evidências do que o ambiente permitir.

Preserve obrigatoriamente:
- identidade canônica do agente fornecida pelo Nexus Server;
- um único Core compartilhado por Server e Connector;
- MCP exclusivamente HTTP direto entre harness e Nexus Server;
- nenhum MCP stdio/HTTP server/client/proxy/SDK/fachada no Core/Connector;
- stdio dos protocolos nativos permitido;
- runtime local no Server sem app Connector;
- autoridade/inbox/handoff/transporte remoto pertencentes aos hosts;
- ownership físico, journal durável, idempotência e OUTCOME_UNKNOWN honesto.

Não passe testes removendo controles, aumentando timeouts indefinidamente,
liberando slots incertos, truncando IDs, descartando modelo explícito,
qualificando builds sem evidência ou habilitando attach por flag.
Não copie adapters, factories privadas ou schemas para outros repositórios.

Porte as sementes de regressão quando a API/lifecycle evoluir, preservando
intenção e rastreabilidade. O teste do fingerprint Pi deve continuar provar
binding local sensível ao path, enquanto a nova build_identity é portável.

Atualize o backlog por tarefa e a matriz com resultados reais. Nenhum PASS/DONE
sem evidência. Fakes não qualificam providers. Não ter Linux/Windows/provider/
outros repositórios disponíveis exige BLOCKED preciso, não PASS nem abandono
de correções locais que podem ser executadas. Produza handoffs quando necessário.

Entregue wheel/sdist locais, hashes/API/NXL/manifest, migração dev0, documentação,
regressões, resultados e relatório final no formato do pacote. Distinga níveis
E0, E1, E2 e E3. Attach pode ficar fora de um preview gerenciado, mas não pode
ser apagado do escopo de conclusão R3. Não publique PyPI/release remoto, não
faça push destrutivo e não altere credenciais/estado de produção.
```

## Arquivos principais

| Arquivo | Finalidade |
|---|---|
| `01_PLANO_CORRECAO_CORE.md` | Especificação técnica integral, sequência, tarefas e aceite. |
| `02_MATRIZ_REGRESSOES.md` | Preparação, ação e resultado de cada cenário RC. |
| `03_HANDOFF_SERVER_CONNECTOR.md` | Integração dos hosts, artefatos e mudanças de contrato. |
| `04_GATES_E_EVIDENCIAS.md` | Níveis de liberação e prova de conclusão. |
| `BACKLOG_CORRECAO.json` / `MATRIZ_TESTES.json` | Estrutura rastreável para execução e atualização de status. |
| `regressoes_originais/` | Nove sementes históricas intactas e runner; podem exigir port de fixtures. |
| `referencias/` | Auditoria original e requisitos R3. |
| `templates/` | Modelos de evidência, handoff e relatório. |
| `ferramentas/validar_plano.py` | Verifica estrutura/dependências do planejamento, não testes do produto. |

A revisão C1 é um plano novo de correção: não é uma nova versão de código nem comprovação de que os defeitos foram corrigidos.
