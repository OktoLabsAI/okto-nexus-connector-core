# Gates, evidências e definição de pronto

## 1. Níveis de entrega

| Gate | Permite | Pré-requisitos | Não permite afirmar |
|---|---|---|---|
| E0 — contrato/preview | Consumidores começarem integração experimental com pin exato e fakes. | Baseline identificado; contratos/API de preview explicitados; bundle e wheel importáveis; comportamento ainda parcial descrito. | Confiabilidade operacional, provider real ou integração distribuída aprovados. |
| E1 — Core corrigido em escopo delimitado | Integrar modos gerenciados nos ambientes de teste qualificados. | F01–F07 tratados no escopo, G01 e IDs resolvidos, qualificação/binding corretos, preflight e backend real do SO-alvo, regressões/conformance/wheel passando. | Attach, todas plataformas, todos providers ou fluxo remoto real sem evidência própria. |
| E2 — integração local e remota | Substituição controlada nos consumidores para as combinações demonstradas. | E1 + Server local sem Connector + fluxo remoto em dois hosts usando mesmo wheel, MCP HTTP direto, recovery e consumo exclusivo. | Escopo R3 inteiro concluído quando attach/outros requisitos prometidos permanecem abertos. |
| E3 — escopo completo | Encerramento do plano de correção e pendências R3 abrangidas. | E2 + PC12 e todas capacidades/combinações declaradas como escopo aceitas, matriz original e complementar fechadas com evidência. | Suporte a builds/SOs fora da matriz testada ou garantias universais de morte/exatamente uma vez. |

E0 pode ser entregue cedo e não equivale a congelar API. E1 pode ser entregue sem esperar PC12. PC14 pode produzir artefato parcial com decisão E1/E2 e backlog pendente; não recebe conclusão integral E3 automaticamente.

## 2. Critérios impeditivos imediatos

Não liberar operacionalmente um escopo em que haja: send impedindo contenção; efeito novo após fence conhecido; stream perdido com novas submissões aceitas; SQLite bloqueando loop do host; ID admitido irrecuperável; uso de import privado obrigatório; modelo explícito descartado; build qualificado apenas por path/versão não verificados; processo externo passível de kill no detach; MCP proxy/server no Core/Connector; migração que apaga estado incerto.

Incerteza explícita sob falha extrema não é defeito por si só. Reportar unknown conservador e reter capacidade pode ser o resultado correto. O bloqueio é mentir sobre o estado, repetir efeito ou perder controle de recursos por suposição.

## 3. Formato de evidência por tarefa

Registrar: task_id; commit(s); descrição da mudança; caminhos alterados; pré-condição; comando exato; exit code; test nodes; SO/arquitetura/Python; versão/build de provider quando aplicável; wheel/manifest SHA; resultado; paths de logs/XML; falhas remanescentes; riscos; relação com F/G/TK/J/RC. Guardar os dados em `templates/EVIDENCIA_TAREFA.json` ou formato equivalente.

Não anexar secrets, dumps completos de env/home, prompts privados, respostas sensíveis do operador ou logs não redigidos. Usar peers/projetos de teste. Diagnóstico de path local só na evidência privada necessária; relatório de handoff deve minimizar dados pessoais.

Estados recomendados: tarefa `PENDING`, `IN_PROGRESS`, `BLOCKED`, `DONE`; teste `NOT_RUN`, `PASS`, `FAIL`, `BLOCKED`. Um teste marcado SKIP na ferramenta é traduzido em NOT_RUN/BLOCKED com razão para o requisito, salvo quando é de plataforma explicitamente fora da campanha e essa limitação está documentada. `NOT_APPLICABLE` exige decisão registrada, não escape de escopo.

## 4. Critérios de qualidade dos testes

Teste de race usa Events/barreiras e relógio injetado, não apenas sleeps. Teste de loop responsiveness contém prova de que timers progridem enquanto o banco está bloqueado. Teste de force prova o backend físico, não só um mock chamado. Teste de unknown conta efeitos no peer antes/depois do retry. Teste de memória remove referências mantidas pela própria fixture antes de inferir leak. Teste de modelo verifica protocolo real quando se declara qualificação, não apenas hash.

Manter os nove casos históricos rastreados: F01; F03; F05; F02; F04; F06; F07/Codex; F07/Claude; observação Pi. A observação Pi deve continuar verdadeira para o binding local, enquanto RC-09-01 exige build portável igual. Não "corrigir" os dois para se tornarem o mesmo hash.

## 5. Matriz original e complementar

A matriz RC possui 129 cenários adicionais/detalhados, inicialmente NOT_RUN. Eles não somam automaticamente 129 testes novos aos 45 TK e 34 J do plano R3: há sobreposição deliberada de cobertura. Registrar relações muitos-para-muitos sem inflar contagem de execuções. Um único teste parametrizado pode demonstrar vários cenários, mas sua camada de evidência precisa corresponder.

Estados do repositório auditado — 27 TK PASS, 18 TK NOT_RUN e 34 J NOT_RUN — são históricos. Atualizar a partir das novas execuções, mantendo proveniência; não sobrescrever histórico com contagem deduzida deste documento.

## 6. Checklist de release local

- Baseline/HEAD e diferenças registrados; nenhuma alteração do usuário perdida.
- F01–F07 com testes e evidência atual; G01–G06 tratados ou escopo/bloqueio explícitos.
- Schema/API/NXL/IDs compatíveis ou migração versionada documentada; dados dev0 preservados.
- Wheel/sdist/manifest e dependências identificados; import/recursos offline e consumers fora da árvore.
- Sem MCP no Core/Connector; stdio nativo e caminho HTTP direto mantidos.
- Docs/modelo/caps/lifecycle correspondem ao código; nenhum `PASS` fictício por mock, platform skip ou provider ausente.
- Handoffs para dois hosts com pin exato e owner das pendências; mesmo artefato nos gates conjuntos.
- Nenhuma publicação PyPI/release/push foi feita sem autorização específica.

## 7. Relatório de encerramento exigido

Usar `templates/RELATORIO_FINAL_AGENTE.md`. A primeira seção deve declarar o nível realmente alcançado (E0/E1/E2/E3) e o escopo de provider/plataforma. Depois: correções, commits/artefatos, execuções, migração, riscos e pendências por owner. Não terminar em “testes verdes” sem dizer quais testes e onde. Se a implementação estiver completa mas a qualificação externa bloqueada, separar esses fatos.
