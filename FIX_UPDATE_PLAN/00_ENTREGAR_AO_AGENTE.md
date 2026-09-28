# Instruções ao agente executor — correção C7

Copie **o pacote inteiro**, com `regressoes/`, `evidencias/`, `backlog.json`, `matriz_aceite.json` e `executar_verificacao.py`, para `plans/correction-c7/` ou diretório equivalente. Não reconstrua testes por descrições quando seus fontes estão disponíveis. O snapshot de referência é `12dae55381a9871958c7ffb7513030eaa66886c2`, pacote `0.2.5.dev0`; trabalhe no HEAD atual, preservando alterações posteriores.

## Prompt pronto

```text
Implemente o plano em plans/correction-c7/02_PLANO_CORRECAO_C7.md.
Leia também 01_RELATORIO_REAVALIACAO.md, 03_MATRIZ_ACEITE.md e os fontes em
regressoes/. O pacote inteiro deve estar disponível; não produza outro
plano em substituição à implementação.

Registre HEAD/dirty state e execute o baseline. Corrija W03 com o supervisor
comum, não com outra cadeia wait_for(close)->force. Corrija W02 mantendo
prova do resultado e token da tentativa no reconciliador; nunca libere
unknown somente por tempo. Corrija W04 pelo caminho público inteiro:
decline/cancel autorizados e correlacionados são diferentes de accept.
Corrija W01 preservando replay de recibos depois de evicção.

Preserve os casos C6 que já passam. Não mude asserções para esconder erros,
não desabilite contenção e não transforme peers sintéticos em qualificação
de providers. Sem MCP stdio, MCP proxy/server ou nova identidade de usuário.
Não copie adapters para os consumidores.

Execute as nove regressões novas e as anteriores, gere wheel/sdist,
valide imports externos e registre evidências por tarefa/cenário. Mantenha
NOT_RUN/BLOCKED quando falta ambiente. Não publique pacote, faça push ou
release sem autorização específica. Conclua com o nível de liberação real
e o escopo testado, não apenas 'testes verdes'.
```

## Comandos de reprodução

Use o ambiente virtual do projeto com as dependências de `pyproject.toml` instaladas. O runner não instala nada nem altera fontes.

```bash
python plans/correction-c7/executar_verificacao.py --repo . --output ./evidence-c7-baseline
python plans/correction-c7/executar_verificacao.py --repo . --output ./evidence-c7-final --full
```

Use diretórios novos para não apagar evidências. O código de saída 1 indica falha de teste; 2 indica setup/timeout/coleção. As regressões negativas têm expectativa correta e falham no snapshot auditado: não são xfail.

A campanha W02 deixa o reconciliador esgotar as 20 tentativas do baseline. Essa espera é intencional para comprovar falta de convergência, não requisito de latência para a implementação corrigida.

## Ordem prática

C7-00 primeiro. C7-01 é a prioridade P1. C7-02, C7-03 e C7-04 podem ser implementadas paralelamente com cuidado nas áreas compartilhadas de runtime.py. Integre tudo antes de C7-05. Server e Connector não precisam esperar para trabalhar em suas áreas independentes, mas não devem contornar os problemas do Core.

## Artefatos finais exigidos

Relatório com baseline/HEAD, commits, diff, comandos, XMLs, hashes e matriz atualizada. Por cenário: camada (unit/fault injection/backend/provider/hosts), teste, resultado e limitações. A campanha de dois hosts não faz parte da prova sintética; E2 depende de evidência própria.
