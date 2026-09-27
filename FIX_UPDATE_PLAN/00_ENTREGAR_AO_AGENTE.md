# Entregar ao agente responsável pelo Core — C4

Copie esta pasta para `plans/correction-c4/` no repositório de trabalho. Preserve os planos anteriores. O snapshot de referência é `8677145c3050b9ba270bc24ae6343d6cb391a168` (v0.2.2.dev0), mas o trabalho deve ocorrer sobre o HEAD atual sem reset nem perda de mudanças posteriores.

## Prompt pronto

```text
Implemente o plano C4 deste diretório. Leia primeiro 01_RELATORIO_REAVALIACAO.md,
02_PLANO_CORRECAO_C4.md, 03_MATRIZ_ACEITE.md e 04_HANDOFF_CONSUMIDORES.md.
Não devolva apenas outro plano: faça as alterações, execute os testes e entregue evidências.

1. Registre HEAD, dirty state e diferenças desde 8677145. Preserve correções posteriores.
2. Incorpore regressoes/test_review4.py como tests/regression/test_c4_audit.py.
   Execute baseline dos arquivos C2/C3 e das dez parametrizações C4 antes de editar.
3. Implemente as 47 tarefas de C4-00 a C4-07, atualizando backlog.json e matrix.json.
   Priorize T01/T03/T04, mas não declare E1 com os P2 do escopo ainda abertos.
4. Corrija as abstrações comuns: contenção não espera journal; guard chega ao write/spawn
   após os locks; OpeningAttempt existe antes da Session e fica fenced no shutdown;
   tentativa CAS tem dono/resultado e não deixa busy permanente; build Pi cobre o layout
   aceito; quotas impedem leitura/enumeração além dos limites.
5. Preserve todas as correções válidas C3. Não crie MCP stdio/server/proxy no Core ou
   Connector; harness usa MCP HTTP direto com o Nexus Server. Identidade é do agente.
6. Não use finally indiscriminado para liberar CAS ainda pendente, cancelamento de await
   como prova de parada de thread, ou unknown como licença para iniciar outra execução.
7. Use barreiras/eventos e relógio inicialmente válido. Não substitua o cenário por
   fence previamente fechado. Se adaptar fixtures, documente a mesma condição causal.
8. Execute os 53 cenários na camada correspondente ou registre BLOCKED/NOT_RUN com motivo.
   Dez sementes são executáveis; os outros 43 são especificações complementares que devem
   ser implementadas ou mapeadas para testes existentes com evidência exata.
9. Qualifique o backend real do SO e providers no escopo. Hosts synthetic embedded/remote
   não demonstram E2. Não remova preflight para fazer o sandbox passar.
10. Gere wheel/sdist em árvore limpa, fixe hashes, teste consumidor -I fora da fonte,
    preserve estado/receipts legados e entregue o handoff de API/lifecycle/algoritmo aos
    dois consumidores. Não implemente correções duplicadas nos outros repositórios.

Resultado final: commits/diff, matriz por T01–T07 e C4T-01–C4T-53, comandos/XMLs,
versões/hashes, EFFECT_BOUNDARIES.md preenchido, limitações e decisão E0/E1/E2/E3
com escopo preciso. Não publique, faça push ou release sem autorização específica.
```

## Execução inicial

Na raiz do repositório, copie a semente com a ferramenta apropriada ao sistema e prepare o ambiente:

```bash
python -m pip install -e ".[test]"
python -m pytest -q tests/regression/test_c2_regressions.py tests/regression/test_c3_regressions.py
python -m pytest -q tests/regression/test_c4_audit.py
```

Os testes novos dependem das fixtures do repositório e do Node para as duas provas de conteúdo. Node ausente é bloqueio dessa camada; não equivale a PASS. O restante não exige login de provider. Qualificação de processo real exige um ambiente que atenda ao preflight.

## Arquivos do pacote

| Arquivo | Utilização |
|---|---|
| 01_RELATORIO_REAVALIACAO.md | Achados, prova, escopo e limites |
| 02_PLANO_CORRECAO_C4.md | Implementação detalhada por tarefa |
| 03_MATRIZ_ACEITE.md | 53 cenários e resultados obrigatórios |
| 04_HANDOFF_CONSUMIDORES.md | Contratos/integração Server e Connector |
| backlog.json / matrix.json | Estado rastreável de tarefas e testes |
| regressoes/test_review4.py | Dez casos executáveis reproduzíveis |
| evidencias/ | Logs, XMLs, comandos, hashes e trechos exatos |
| templates/ | Registro de evidência e relatório final |

Não copie `evidencias/changes.diff` como patch de correção: ele é somente a diferença histórica entre as duas versões recebidas.
