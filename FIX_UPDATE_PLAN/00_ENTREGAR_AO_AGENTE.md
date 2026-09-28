# Entrega ao agente — correções C6 do Core

**Baseline auditado:** `df3baaf77f941485f697ff4424af17ada10b36fc`, versão `0.2.4.dev0`.

## Como entregar

Extraia **o ZIP inteiro** numa pasta do repositório, por exemplo `plans/review-c6/`. Não copie somente os Markdown: `regressoes/` contém as seis reproduções novas e as onze sementes originais C5; `backlog.json` e `matriz_aceite.json` preservam os IDs do trabalho. O executor anterior registrou que recebeu apenas quatro documentos e reconstruiu as sementes; este pacote elimina essa necessidade.

Leia, nesta ordem: relatório, plano, matriz. Depois execute o runner em um ambiente de teste com as dependências do projeto. O runner não instala pacotes, não corrige o produto, não desliga a contenção e não publica nada.

```bash
python plans/review-c6/executar_verificacao.py --repo . --output ./evidence-c6-baseline
```

Para executar somente as novas reproduções:

```bash
python plans/review-c6/executar_verificacao.py --repo . --output ./evidence-c6-new --group new
```

Para acrescentar a suíte completa do produto:

```bash
python plans/review-c6/executar_verificacao.py --repo . --output ./evidence-c6-full --full
```

No snapshot auditado, seis novas parametrizações falham, C5 entregue tem 11 PASS e C5 original tem 10 PASS/1 FAIL menor. Depois de corrigido, o resultado esperado é as seis passarem, além da correção incremental M01 e dos critérios complementares relevantes. Ausência de dependência ou backend de SO não é a mesma coisa que uma falha causal do produto.

## Prompt pronto

```text
Trabalhe no HEAD atual do okto-nexus-connector-core, sem reset e sem perda
 de alterações existentes. O snapshot da auditoria é df3baaf, versão
0.2.4.dev0; ele é referência, não ordem para retornar ao commit.

Leia 01_RELATORIO_REAVALIACAO.md, 02_PLANO_CORRECAO_C6.md,
03_MATRIZ_ACEITE.md, backlog.json e os testes deste pacote inteiro.
Implemente as correções — não produza outro plano como substituição.

O escopo é restrito: V01 (revogação incerta ainda permite trabalho em
caminhos tardios/read indisponível), V02 (produtor/handle tardio sem
ownership/lifecycle completos), V03 (resposta comprovadamente não escrita
consome pedido de aprovação) e M01 (um nome a mais na enumeração limitada).
Não refaça tudo nem invente funcionalidades. Preserve as correções C5.

Comece por registrar HEAD/dirty state e executar as sementes. Não
reconstrua os testes apenas por seus nomes: os arquivos executáveis estão
em regressoes/. Alterações justificadas de fixtures são permitidas, com
diff e condição causal preservada. Não inverter asserções, remover casos,
marcar xfail/skip para ocultar defeito ou usar stub de rfc8785.

Execute C6-00, corrija C6-01/C6-02 como máquinas de estado compartilhadas
por todos os caminhos, complete C6-03 e feche C6-04. São 27 tarefas e 37
cenários de aceite. Um cenário NOT_RUN não vira PASS por existência de
função ou por teste parecido. Estado de tarefa e de teste são separados.

V01 exige finalizador único direto/tardio, tentativa identificada e hold
produtivo separado de CAS_BUSY. Commit com confirmação perdida não é
rollback. Cancelar o chamador não cancela a obrigação de reconciliar.

V02 exige guardar produtor/guarda/handle até resolução ou transferência
explícita. Shutdown deve alcançar open mesmo depois de cancelar o waiter.
Handle tardio deve entrar no supervisor comum: close/observe travados não
podem impedir força. Unknown conserva o handle, não somente um ID.

V03 exige reserva do pedido sem consumo antecipado. Recusa comprovada
antes de bytes permite desfazer só a própria reserva, mantendo correlação
válida. Depois de write/flush possível, não restaurar PENDING nem reenviar
às cegas. Deny do pedido ainda válido continua permitido.

Não reintroduza MCP stdio, proxy/servidor/relay MCP. Harnesses MCP usam HTTP
direto no Nexus Server. Não crie usuário Nexus, não copie adapters nos
consumidores, não mude o transporte remoto como parte desta correção.

Execute testes históricos, reproduções novas, cenários complementares e
campanha real no SO que será anunciado. Gere wheel, instale fora da fonte
e teste consumidores. Synthetic remote_consumer não comprova dois hosts.
Não classifique as falhas de proc_children deste sandbox como 123 bugs.

Entregue commits, diffs, comandos, XMLs, hashes, mudanças públicas de
contrato, estados dos 27 itens e 37 cenários, limitações e decisão E0/E1/E2.
Não declare E1 nos caminhos V01/V02 enquanto as garantias falharem.
Nenhum push/publicação/release é autorizado por este pedido.
```

## Critério de encerramento

Três grupos reais, não seis patches isolados. A diferença M01 é pequena e não bloqueia E1 sozinha. O resultado esperado é encerrar os fluxos causais e seus equivalentes, sem ampliar o escopo para E2/E3 ou suporte universal. As campanhas de provider/SO e a integração dos produtos precisam de evidência própria, não inferida de unit tests.
