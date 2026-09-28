# Entregar o pacote completo ao agente

O snapshot revisto é `c5bd9557861f44577ae8dbf5585790acfd045fa5` (`0.2.8.dev0`). Há uma correção residual de lifecycle comprovada por dois testes e uma parte funcional do C9 ainda não entregue. O catálogo público existente foi validado; não refazê-lo.

Copie o ZIP inteiro para uma pasta de trabalho do repositório, preservando `regressoes/`, `evidencias/` e os documentos. Os testes desta revisão não estão contidos apenas na descrição Markdown.

## Prompt

```text
Leia 01_RELATORIO_VALIDACAO.md, 02_PLANO_COMPLEMENTAR_C10.md e
03_MATRIZ_ACEITE.md. Trabalhe no HEAD atual sem reset e sem perder
alterações posteriores ao snapshot c5bd955.

Execute executar_verificacao.py antes de editar. Implemente C10:
1. conclua a avaliação técnica pública por candidato prevista em
   C9-01.4, reaproveitando catálogo/registry/qualificação/preflight;
2. preserve o produtor durável da liberação quando o shutdown esgotar
   sua espera, inclusive se o cancelamento do backend precisar aguardar.

Não replique listas/regras nos consumidores, não exponha classes ou
credenciais, não crie MCP stdio/proxy e não reescreva os adaptadores.
Mantenha Y01/Y02 e os controles anteriores. Novos nomes de API são
livres, mas devem ser públicos, tipados e consumíveis no wheel.

Entregue correções executadas, testes, diff, versões e evidências,
não outro plano. Não declare qualificação de provider/SO ou E2 a
partir de peers sintéticos. Separe READY técnico da autorização do
agente que continua no Server.
```

## Executar reproduções

Com as dependências de teste já instaladas no ambiente do Core:

```bash
python executar_verificacao.py --repo /caminho/do/core --output /caminho/das/evidencias
```

O runner não instala dependências, não escreve no produto e não desliga contenção. No snapshot atual são esperadas duas falhas; depois da correção devem passar. A matriz inclui verificações de disponibilidade ainda a implementar: não são testes arbitrários de presença de uma função com nome imposto.
