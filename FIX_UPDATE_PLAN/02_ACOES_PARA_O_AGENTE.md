# Próxima rodada de correção — achados S01–S08

## Instrução ao agente

Trabalhe sobre o HEAD atual do `okto-nexus-connector-core`. O snapshot auditado foi `7a7a248db695296bb92b3f681791cc6eb2dea8c7`, versão `0.2.1.dev0`. Não faça reset para esse commit nem apague trabalho posterior. Leia o relatório, a decisão C1 e as evidências C2. Confronte cada achado com o código atual antes de alterar.

Implemente as correções, não outro plano em substituição à execução. Preserve o trabalho válido: composição pública, DTO de resume, discovery Pi por parâmetros públicos, recibos idempotentes, sinalização coalescida, guarda de send, preflight ativo e cleanup cooperativo. As novas falhas não justificam reescrever a biblioteca.

Não reintroduza MCP stdio, proxy ou servidor MCP. Harnesses capazes de MCP acessam diretamente o Nexus Server por HTTP. Identidade continua centrada no agente. Os hosts não devem copiar adapters nem importar a factory privada para contornar pendências.

## A00 — Reproduzir, mapear e preservar

1. Registre HEAD, branch, dirty state e versão do wheel. Identifique correções posteriores ao snapshot sem sobrescrevê-las.
2. Execute as 14 sementes C2 e as 11 regressões deste pacote. Preserve os resultados anteriores em vez de substituí-los.
3. As novas regressões começam com expectativas corretas e falham no snapshot. Corrija o produto; não inverta asserções, remova caminhos ou crie skips para declarar êxito.
4. Mudanças justificadas de API/fixtures são permitidas: registre antes/depois e mantenha a mesma condição causal. Os testes devem começar autorizados, atravessar a espera e vencer durante a espera — não nascer com fence fechado.
5. Separe unitário, fault injection, backend real do SO, provider real e integração de hosts. Uma camada não concede qualificação automática à outra.
6. Crie matriz S01–S08 com `PENDING`, commits, testes, evidências e risco residual. Um cenário já corrigido no HEAD precisa de evidência, não retrabalho.

**Saída:** baseline rastreável e todas as alegações correlacionadas com testes/requisitos.

## A01 — Fonte temporal única e default seguro (S01)

- Resolva o relógio efetivo na composição pública antes de criar a factory e o runtime. Sem argumento de teste, utilize a fonte real apropriada ao mesmo contrato.
- Compartilhe deadline/tempo entre kernel, runtime e native bridge, sem conversões de relógios incompatíveis.
- Elimine a interpretação de `None` como “desligar a proteção de validade”. A segurança do default deve ser igual à de uma instância com relógio injetado.
- Reavalie depois de environment, resume e ação nativa. Teste tanto callbacks rápidos quanto atrasados.
- Não converta erro posterior a possível spawn em `retry_safe=True`. Preserve estágio, recibo e desconhecimento quando houver efeito possível.

**Aceite obrigatório:** S01 passa com composição pública sem clock, e os cenários com clock injetado continuam passando. Inclua testes reais de passagem do prazo usando margem/temporização estável, além de relógios controlados.

## A02 — Guarda no efeito físico e não só no enfileiramento (S02–S03)

- Crie uma política comum para cada operação com efeito: spawn, submit, steer, input, resposta permissiva de aprovação e demais writes realmente expostos.
- Passe a guarda até a unidade de trabalho síncrona que efetua o write/spawn. Verifique-a quando a thread começar, e após esperas adicionais que existam antes do efeito.
- A guarda deve considerar deadline atual, revogação, geração de owner/conexão, sessão/turno esperado e configuração/autorizações pertinentes. Não utilize somente flags atualizadas por um watcher periódico.
- Diferencie efeitos que concedem trabalho/permissão das ações necessárias para negar, interromper e conter. Defina explicitamente o que continua permitido após expiração.
- Revalide correlação do pedido de aprovação e turno na escrita. Não permita que um callback antigo autorize uma execução nova.
- Trate a janela inevitável entre observação e efeito conservadoramente; não prometa atomicidade com um provider externo nem execução exatamente uma vez.
- Teste worker ocupado antes do despacho, callback tardio, mudança de geração enquanto a unidade aguarda, expiração com watcher atrasado e fechamento concorrente.

**Aceite obrigatório:** S02 e S03 passam; testes R03 antigos continuam passando; matriz de cada write identifica sua fronteira real. Nenhuma proteção depende de aumentar o polling do watcher.

## A03 — Remover armazenamento das travas de contenção (S04)

- Faça inventário de todos os `async with self._lock`, locks de sessão e caminhos que podem impedir a entrada da força. Inspecione chamadas indiretas, não apenas nomes contendo `journal`.
- Retire CAS de renovação/revogação das seções críticas de segurança. Faça reserva/revisão em memória curta, I/O fora da trava e revalidação de estado ao aplicar o resultado.
- Preserve a decisão conservadora enquanto o CAS está pendente. Não expanda permissões antes da confirmação necessária; não reabra um fence já fechado por outra operação.
- Especifique a corrida: CAS aceito pelo worker, chamador cancelado, commit tardio, expiração/contenção concorrentes. A resposta não pode alegar ausência de efeito apenas porque o `await` foi cancelado.
- Mantenha recuperação a partir do journal, mas não torne a solicitação de força dependente de uma gravação bem-sucedida.
- Teste concorrência entre renew/revoke, CAS retido, cancelamento, shutdown e nova tentativa com a mesma ou outra geração.

**Aceite obrigatório:** ambas as parametrizações S04 passam, com CAS retido durante toda a observação da entrada física de força. Não basta esperar pelo timeout de reconexão configurado. Adicione fault point de commit tardio e teste de recuperação.

## A04 — Capacidade de força não consumível por observação/close (S05)

- Mantenha limites de recursos e o pool de dados separado. Reprojete as classes de trabalho de controle para que consultas de estado e fechamento gracioso não ocupem toda a capacidade de força.
- Reserve mecanismo/capacidade de dispatch para força com orçamento independente; uma prioridade na fila não resolve workers que já estão executando chamadas bloqueadas.
- Coalesça observações por sessão, evite acúmulo de polls obsoletos e limite filas/concorrência.
- Não use thread ilimitada por timeout, tentativa ou sessão. Defina limites de sessões compatíveis com a capacidade física do backend.
- O bloqueio real da chamada de força no SO deve gerar estado incerto explícito e contenção/reconciliação posterior; não inventar comprovação de parada.
- Teste pool default saturado, todos os observers ocupados, vários closes bloqueados, força repetida e fechamento do host.

**Aceite obrigatório:** S05 e a semente R02 passam. A evidência deve observar a função física de força começar, não somente a coroutine que pretende chamá-la.

## A05 — Lifecycle público dos executores (S08)

- Declare propriedade: recursos criados pela composição pública são encerrados por um lifecycle público; recursos injetados pelo host seguem contrato explícito de ownership.
- Feche/disponha o executor interno após shutdown completamente resolvido, de modo idempotente, sem acesso a atributos privados pelo consumidor.
- Não descarte capacidade de força/observação ainda necessária a sessões incertas. Defina shutdown parcial, retry, reconciliação e final disposal separadamente quando necessário.
- Teste sem sessões, com sessões confirmadas, com ownership incerto, dois shutdowns, cancelamento do shutdown e ciclos repetidos create/shutdown.
- Verifique a ordem da flag `_closed` em sessões que possuem pool próprio: a decisão de descarte deve usar o resultado recém-observado, não um estado anterior inadvertido.

**Aceite obrigatório:** S08 passa sem o host chamar `_native_factory.close()`. Testes de estados incertos demonstram que a correção não destrói o supervisor prematuramente.

## A06 — Código de erro estável e diagnóstico separado (S07)

- Preserve `CoreError.code == "PROCESS_CONTAINMENT_UNAVAILABLE"` em qualquer host.
- Transporte o mapa de requisitos/causas em mensagem ou campo estruturado documentado, com redaction. Não concatene detalhes no enum de código.
- Atualize o contrato público e os consumidores de serialização de forma coordenada, caso precise ampliar o modelo de erro.
- Teste igualdade exata, conversão para JSON/recibo/erro NXL aplicável, apresentação da CLI e ausência de caminhos/segredos desnecessários.
- Preserve a recusa antes do probe e a ABI corrigida. Não remover o gate para satisfazer este teste.

**Aceite obrigatório:** S07 e R07/R07b passam; detalhes continuam úteis sem quebrar a classificação programática.

## A07 — Conteúdo do build Pi realmente qualificado (S06)

- Defina o layout suportado e o que constitui seu fechamento de conteúdo executável. Escolha entre bundle comprovadamente autocontido ou cobertura limitada e completa do pacote/dependências necessárias.
- Cubra resolução implícita, exports, imports relativos, arquivos auxiliares e artefatos nativos quando fizerem parte do layout suportado. Não tratar `main`/`bin` como todo o código de uma dependência.
- Preserve limites de bytes/entradas/profundidade/pacotes e diagnóstico de layout não suportado. Não execute pacotes desconhecidos para “descobrir” o conteúdo com permissões amplas.
- Mantenha a separação: identidade portátil de build versus fingerprint de binding/caminho local. Pacote irmão não utilizado continua fora da identidade.
- Versione o algoritmo quando a semântica mudar. Requalifique deliberadamente a allowlist e documente o efeito sobre candidatos preparados/configurações antigas.
- A qualificação não pode usar version string ou digest parcial como substituto silencioso quando não consegue representar o layout.

**Aceite obrigatório:** as três parametrizações S06 passam; alterar arquivo realmente carregado muda identidade; mudar somente diretório preserva identidade portátil; binding físico continua detectando drift; package irmão irrelevante não muda o build. Execute e registre a requalificação real do Pi antes de anunciar suporte ao build.

## A08 — Evidência de fechamento e integração dos consumidores

1. Preserve os 14 cenários C2 e acrescente os 11 novos sem duplicar contagens no relatório da suíte.
2. Execute o conjunto completo em backend Linux compatível e na matriz de SO/Python realmente declarada. Separe incompatibilidade do sandbox de falha do produto.
3. Gere wheel/sdist, instale fora da árvore-fonte e execute consumidores sintéticos e import público. Isso não substitui os hosts reais.
4. Teste o contrato de erro, callbacks, relógio e disposal sem import privado nos consumidores de contrato.
5. Revise as afirmações C2 “nenhum I/O sob lock”, “guarda na fronteira de spawn”, “build completo” e “pool disposto”. Cada uma precisa apontar para testes dos caminhos relevantes.
6. E1 só pode ser emitido para um escopo com S01–S08 tratados, qualificações pertinentes e evidências coerentes. E2 exige Server local sem Connector e fluxo remoto real; E3 inclui demais capacidades prometidas.
7. Entregue commits, diff, regressões, comandos, XMLs, hashes, limites de suporte, alterações de contrato e decisão explícita. Não declare “concluído” somente por 14 testes verdes.

## Prompt pronto para iniciar

```text
Leia 01_RELATORIO_REAVALIACAO.md, 02_ACOES_PARA_O_AGENTE.md e os testes
regressoes/test_review3.py deste pacote. A referência auditada é 7a7a248,
mas trabalhe sobre o HEAD atual sem reset nem perda de alterações.

Implemente A00–A08. Priorize S01–S05, preserve as correções válidas C2 e
não contorne problemas nos consumidores. Execute as regressões, documente
mudanças de fixture necessárias sem enfraquecer invariantes e registre
evidência de cada achado. Não crie MCP stdio/proxy. Não use testes
sintéticos como prova de provider real ou integração de dois hosts.

Antes de declarar E1, demonstre defaults seguros, guardas no efeito,
contenção independente de journal/observers, disposal público, erros
estáveis e cobertura correta do build Pi. Separe explicitamente o que
passou, o que não foi executado e o que permanece bloqueado.
```
