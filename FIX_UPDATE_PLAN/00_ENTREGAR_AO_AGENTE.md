# Entrega ao agente — C9

Copie este diretório inteiro, incluindo `regressoes/`, para uma pasta de planejamento do repositório. Não entregue somente os Markdown. As correções C8 passaram na auditoria; preservar os avanços.

## Prompt

```text
Leia 01_RELATORIO_VALIDACAO.md, 02_PLANO_C9_CATALOGO_E_RECUPERACAO.md e
03_MATRIZ_ACEITE.md. Trabalhe sobre o HEAD atual do Core, sem reset para a
referência 6a43e90 (0.2.7.dev0) nem perda de alterações posteriores.

Implemente as correções Y01/Y02 e publique o catálogo de runtimes C01.
A fonte única deve ser o registro do Core, com projeção pública sem detalhes
de carregamento; Server, Connector e UI não mantêm arrays autoritativos.
Separe conhecido, instalado, qualificado, pronto para runtime e autorizado
para binding. Não criar MCP stdio, servidor/proxy MCP ou protocolo remoto
novo no Core.

Execute as regressões fornecidas e preserve C8/C7. No retry de força,
uma observação bloqueada não pode impedir a contenção sobre recurso próprio.
Não regredir a coalescência de força física. No release persistente, o prazo
do shutdown encerra só a espera, mantendo obrigação/produtor e recuperação.

Os agentes de Server e Connector podem desenvolver em paralelo consumindo o
contrato público. Entregue primeiro a API do catálogo, depois wheel pinado
com os reparos. Não compense gaps nos hosts copiando adapters/imports privados.

Registre testes/camadas, XMLs, hashes, mudanças de contrato e pendências.
Testes sintéticos não qualificam provider real nem integração de dois hosts.
Não marque NOT_RUN/BLOCKED como PASS. Não publique release sem autorização.
```

## Executar

Instale no ambiente de trabalho as dependências reais do projeto e de teste. Depois:

```bash
python executar_verificacao.py --repo /caminho/do/core --output /caminho/evidencias
```

O runner não instala dependências, não modifica fontes e não remove gates de contenção. Nesta auditoria, os dois testes C9 falham; C8 original tem cinco PASS e C7 original nove PASS. Contagens de campanhas repetidas/subconjuntos não somam ao total da suíte.

## Conteúdo

`01_RELATORIO_VALIDACAO.md`: resultado e decisão.  
`02_PLANO_C9_CATALOGO_E_RECUPERACAO.md`: trabalho explícito por fase.  
`03_MATRIZ_ACEITE.md`: 24 cenários com camadas/estados.  
`regressoes/`: testes C9 e sementes originais C8/C7.  
`evidencias/`: logs, XMLs, observação do catálogo, trecho de código e hashes.  
`artefatos/`: wheel/sdist gerados na auditoria, sem correções; não são a futura versão C9.
