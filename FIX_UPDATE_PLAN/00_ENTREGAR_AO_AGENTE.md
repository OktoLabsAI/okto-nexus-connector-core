# Entrega ao executor — ajuste localizado C11

Levar o ZIP inteiro, incluindo `regressoes/` e `executar_verificacao.py`. Não basta entregar os Markdown. Há um único achado P2, não uma nova reformulação de arquitetura. Catálogo, avaliação e shutdown corrigidos devem ser preservados.

## Prompt pronto

```text
Leia 01_RELATORIO_VALIDACAO.md, 02_PLANO_C11_IDENTIDADE_DA_INSTALACAO.md
 e 03_MATRIZ_ACEITE.md deste pacote completo.
A referência auditada é 6909435ff0d913cda03494f26bda670e2d3e75b0,
versão 0.2.9.dev0. Trabalhe sobre o HEAD atual, sem reset nem perda
 de alterações posteriores.

Implemente C11-00 a C11-03 para A11-01: duas instalações distintas com
os mesmos bytes precisam ser selecionáveis/resolvíveis sem ambiguidade.
Preserve a mesma identidade de BUILD para bytes iguais; não altere
fingerprints de qualificação, identidade/chaves do agente ou hashes
de operações para mascarar a colisão. A referência da instalação e sua
revisão/escopo são conceitos separados. Não use índice do array.

Use API pública, mantenha a fonte única do catálogo e publique um caminho
 de resolução para os dois consumidores. Versione a projeção/migração
se a semântica de candidate_ref mudar. Uma ref legada ambígua exige
resseleção, não escolha do primeiro binário. Não implemente MCP/proxy.

Execute as regressões e controles. O runner atual apresenta 2 FAIL e
15 PASS neste snapshot; os dois FAIL são parametrizações de um achado.
Mantenha os históricos de shutdown verdes. Falta de proc_children não é
motivo para remover contenção nem para declarar provider qualificado.
Entregue diff, contrato, wheel, hashes, XMLs, limites e decisão por escopo.
Não produza somente outro plano: implemente e comprove o ajuste.
```

## Execução

```bash
python executar_verificacao.py --repo /caminho/do/core --output /caminho/das/evidencias
```

O runner usa as dependências do ambiente (`pytest`, `rfc8785`, `jsonschema`) e
não faz instalação, rede, push, rotação de credenciais nem alteração do produto.
Ele pode retornar não zero antes da correção: as expectativas corretas dos dois
casos novos falham no snapshot. Os testes usam arquivos de laboratório e peers
controlados; não chamam providers reais.
