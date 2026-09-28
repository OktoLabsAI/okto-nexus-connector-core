# Executar correções C5 — instrução pronta

Copie **o pacote inteiro**, incluindo regressoes/, evidencias/, backlog.json e matriz_aceite.json, para uma pasta de planejamento do repositório ou forneça seu caminho ao agente. Não é suficiente copiar só este Markdown. Os testes importam helpers do próprio repo; devem ser executados com root e src no PYTHONPATH pelo runner.

## Prompt

```text
Você é o executor do nexus-connector-core. Leia 01_RELATORIO_REAVALIACAO.md,
02_PLANO_CORRECAO_C5.md, 03_MATRIZ_ACEITE.md e regressoes/test_review5.py
DESTE PACOTE. A referência auditada é 3d304f9ccb1982f71410acb0a0622b0b8685a06f, 0.2.3.dev0,
mas trabalhe sobre o HEAD atual sem reset nem perda de alterações posteriores.

Implemente C5-00 a C5-07 (48 tarefas). Não substitua a execução por outro plano.
Antes de editar, reproduza os 11 casos novos: no baseline há dez FAIL e um PASS.
Os 16 testes C4 entregues e as dez sementes C4 originais adaptadas passaram na
auditoria; preserve-os. Adapte fixtures somente para API/causalidade legítima,
registrando o diff. Nunca inverta asserts, use skip/xfail ou ignore erro para
concluir uma tarefa.

Prioridade: guardas por operação no writer de approvals e no spawn DEPOIS de
locks; supervisor do Future/handle de open cancelado; antecipação da força;
CAS pós-commit incerto; conjunto real de artefatos Pi e scanner incremental.
Não mantenha apenas markers sem produtor associado. Não infira rollback de
Future.done()/Exception. Não deixe contenção depender de storage/observers.

Preserve MCP HTTP direto harness→Server, identidade centrada no agente e
Core único compartilhado. Nada de MCP stdio, proxy/servidor MCP, novo cadastro
de usuário, cópia de adapter no host ou imports privados no consumidor.

Atualize backlog e matriz com commits/tests/evidências. Revise PASSs C4 que
usam cenário diferente ou inspeção de código como prova. Registre plataforma,
Python, provider/build quando real, comandos/XMLs, wheel/sdist/manifest SHA,
contratos/migrações e limites. Gate de SO não pode ser removido para aprovar
ambiente incompatível.

E1 exige os P1 resolvidos e evidência no escopo qualificado. E2 exige Server e
Connector REAIS em dois hosts, além de modo local sem Connector. Smokes de
wheel, peers e schemas não provam isso. Não publique/push sem autorização.
```

## Ordem operacional

Começar em C5-00; depois C5-01/02. C5-06 pode avançar independentemente após baseline. Integrar C5-03/04 e C5-05 antes da campanha C5-07. Os outros repositórios podem trabalhar em E0 com pin, mas não contornar esta biblioteca.

## Condição de encerramento

Resposta do agente precisa dizer o que corrigiu e provou, o que não executou, riscos e gate alcançado. Mudar somente o texto da decisão E1 sem corrigir o produto não atende. Código sem evidência exigida também não encerra qualificação. Não há promessa de que 11 testes cubram todas as falhas possíveis: os 56 cenários detalham a campanha necessária.
