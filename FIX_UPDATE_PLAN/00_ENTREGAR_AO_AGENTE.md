# Instruções de execução — C8

Copie **todo o pacote**, incluindo regressoes, para o repositório ou mantenha-o em pasta acessível ao executor. Os Markdown não contêm os testes executáveis. O objetivo é implementar as três correções no HEAD atual, não gerar novo plano.

## Prompt pronto

```text
Trabalhe no HEAD atual do okto-nexus-connector-core. Leia 01_RELATORIO_REAVALIACAO.md,
02_PLANO_CORRECAO_C8.md e 03_MATRIZ_ACEITE.md. A referência auditada é
9f0ebabcfb314f3f2da2221467d16a85134e475e / 0.2.6.dev0; não faça reset.

Implemente C8-00 a C8-04. Priorize X01 (contexto antigo aceito depois de observar
fence durável mais novo), e feche X02/X03 no MESMO coordenador de recursos tardios:
obrigação de release durável preservada e força física coalescida.

Execute primeiro os testes reais do pacote. Preserve as nove sementes C7, os dois
controles positivos C8 e a prova stage=lease_cas. Em X03, a primeira thread precisa
continuar ativa ao observar a segunda chamada. Não substituir por mocks que
recusam antes da fronteira, não xfail, não remover guards e não reescrever adapters.

Não use producer_done como prova de rollback, não limpe estado após erro de ledger
e não confunda cancelamento de await com término do produtor físico. Não conserte
isso nos consumers, com atributos privados ou cópia de código. Preserve MCP HTTP
direto no Server, identidade do agente, stdio nativo e ausência de proxy MCP.

Atualize tarefas e matriz com commits, test nodes, comandos, XMLs, hashes e limites.
Reporte qualificação real separada de peers sintéticos. E1 precisa dessas garantias
no escopo declarado; E2/E3 não são demonstrados por smokes do wheel. Não publique
release sem autorização. Entregue implementação e evidências, não outro plano.
```

## Verificação inicial

Com Python >=3.11, pytest e as dependências reais do pyproject já instalados:

```bash
python executar_verificacao.py --repo /caminho/okto-nexus-connector-core --output /caminho/evidencias-c8-inicial
```

O runner não instala dependências, não modifica fonte de produto e não desliga contenção. Ele executa C8 e C7 original; `--historical` acrescenta a campanha histórica e `--full` a suíte completa. Cada saída deve ser uma pasta nova. Repita contra o código corrigido em outra pasta.

No baseline: C8 = 3 FAIL / 2 PASS; C7 original = 9 PASS. Falha de import/setup é distinta de falha funcional. Os testes usam peers limitados e teardown que libera todos os workers. Uma finalização por timeout do processo de testes não comprova parada de quaisquer recursos nativos; consulte logs.

O pacote inclui resultados prévios e rascunhos separados em evidencias/preliminares. Somente validated_new/validated_repeat são as reproduções finais C8. As duas fontes rfc8785 utilizadas pelo auditor foram conferidas pelos hashes Git; não há stub no pacote e o executor usa a dependência normal de pyproject.
