# Revalidação do Core — 0.2.9.dev0

## Decisão

**Avançar com o desenvolvimento do Nexus Connector e da integração no Nexus Server.** A avaliação pública por candidato agora existe, reutiliza políticas do Core e fornece uma projeção versionada. Os cenários originais de cancelamento/prazo da liberação durável passaram. Nesta revisão não foi reproduzido um novo bloqueador P1 de execução ou contenção.

Há **um achado funcional P2, A11-01**: a referência pública não diferencia duas instalações distintas de Codex ou Claude com os mesmos bytes. Corrigir antes de dar aceite ao binding que seleciona uma instalação específica entre múltiplas opções do mesmo adaptador. Isso não exige nova arquitetura nem impede integrar catálogo, estados técnicos, daemon, identidade e comunicação.

Não confundir essa decisão com liberação operacional universal: a suíte completa não passou neste ambiente, e não houve qualificação de provider real, Windows/WSL2 ou dos aplicativos reais em dois hosts.

## Escopo e fonte

ZIP `okto-nexus-connector-core-main(8).zip`; comentário Git do arquivo: `6909435ff0d913cda03494f26bda670e2d3e75b0`; pacote `0.2.9.dev0`. Comparação com `c5bd955`/`0.2.8.dev0` e plano C10. Foram comparados os arquivos, inspecionadas as mudanças de disponibilidade e release, executadas sementes históricas, a suíte completa e uma reprodução adicional pelo discovery público. Os 422 arquivos originais foram verificados por SHA-256 e permaneceram iguais.

## O que foi validado positivamente

A superfície pública fornece `get_runtime_catalog`, `RuntimeCatalog`, `RuntimeDescriptor`, `evaluate_runtime_availability`, `AvailabilityReport`, `CandidateAvailability` e `AVAILABILITY_FORMAT_VERSION`. O avaliador consulta o catálogo, a política real de qualificação de build e o preflight do host. Não implementa servidor/proxy MCP nem lógica canônica de autorização do agente. Não tornou attach qualificado.

Estados como NOT_PROBED e CONTAINMENT_UNAVAILABLE continuam restritivos; READY_FOR_RUNTIME descreve um resultado técnico, não autorização do agente nem garantia de que uma chamada posterior não detectará drift. A projeção `to_dict()` omite os caminhos de executável/script das entradas padrão do discovery. Constatou-se repetibilidade com o mesmo inventário.

A separação do produtor durável de `_cleanup_tasks` foi efetiva nos cenários originais C10: o backend não recebeu cancelamento pelo prazo do shutdown, a espera pública retornou com a barreira ainda fechada e o produtor continuou acompanhado. Os controles entregues de cancelamento externo, conclusão tardia, confirmação perdida e independência entre recursos também passaram.

## Resultados executados

| Campanha | Resultado |
|---|---|
| C10 do executor: disponibilidade + recuperação | 17 PASS, 3 FAIL |
| Parte de recuperação do C10 do executor | 7 PASS (subconjunto acima) |
| Sementes originais C10/C9 + testes C9 entregues, runner anterior | 12 PASS |
| Histórico C2–C9 dentro da suíte completa | 82 PASS, 1 SKIP |
| Suíte completa | 728 PASS, 126 FAIL, 20 SKIP, 2 warnings |
| Novas verificações de identidade | 2 FAIL, 3 PASS |
| Repetição das verificações de identidade | 2 FAIL, 3 PASS |
| Mesmas verificações com wheel instalado e Python -I | 2 FAIL, 3 PASS |
| Wheel + sdist, import isolado, bundle, consumers embedded/remote | PASS |
| Regeneração de 10 JSONs de contrato em cópia separada | Bytes idênticos |

**Contagens não aditivas:** os históricos e o C10 entregue já estão dentro da suíte completa. Repetições não acrescentam cobertura distinta. Os dois testes adicionais que falham demonstram um único achado em dois adaptadores.

### Falhas ambientais e precisão da comparação

Os 126 nomes de teste que falharam foram comparados com os 123 nomes do XML da revisão anterior: os 123 anteriores reaparecem, e os três nomes novos são testes unitários de disponibilidade que assumem contenção disponível. O ambiente informa ausência de `/proc/self/task/<pid>/children`; o avaliador corretamente retorna CONTAINMENT_UNAVAILABLE, em vez de READY ou PREPARATION_REQUIRED. Não se deve remover o gate para fazer esses testes passar. Isolar o preflight nos testes unitários e manter uma campanha real de plataforma é uma melhoria de testabilidade, não outro defeito funcional de disponibilidade.

Os dois warnings vêm de doubles antigos que definem `close` assíncrono onde a bridge espera fechamento síncrono (`_ClockLateNative`, `_SlowThreadNative`). Foram registrados; não foram promovidos a nova falha do produto.

As campanhas Windows/WSL2 presentes no ZIP pertencem ao executor e não foram reproduzidas. Seu ambiente/relógio e artefatos não são evidência de uma execução deste revisor. O manifesto permanece development-partial.

## A11-01 — Referência ambígua entre instalações idênticas

**Prioridade:** P2. **Impacto:** seleção/binding por candidato; não comprova execução indevida, vazamento de credencial ou falha de autorização.

Âncoras do snapshot:

- `src/nexus_connector_core/availability.py:63–89`: DTO e documentação admitem a referência compartilhada por duas instalações.
- `availability.py:236–249`: `candidate_ref=candidate.fingerprint`.
- `src/nexus_connector_core/discovery.py:58–63`: fingerprint de executável é SHA-256 dos bytes.
- `discovery.py:candidate/discover_path`: caminhos diferentes continuam sendo candidatos distintos.
- `docs/api.md:14,152–179`: referência proposta para binding e contrato dos consumidores.

### Reprodução e causalidade

A fixture cria dois diretórios e copia o mesmo executável de laboratório para cada um, com nomes reconhecidos pelo discovery (codex ou claude). Não executa o arquivo nem chama providers. Usa `LocalRuntimeCore.discover(DiscoveryRequest((adapter_id,)))` pela API pública, com raízes confiáveis explícitas e uma factory que proibiria qualquer open. Em seguida chama `evaluate_runtime_availability(inventory)` e `to_dict()`.

O discovery retorna dois candidatos, com caminhos locais diferentes e mesmo conteúdo. Na projeção ambos têm o mesmo adapter_id, candidate_ref, versão não observada, confiança e estado. As duas linhas serializadas são literalmente iguais. Para o mesmo executor e revisão, o tuple proposto para binding não consegue expressar qual instalação foi escolhida.

A prova foi repetida para codex_app_server e claude_stream. Três controles passaram: builds diferentes já recebem referências diferentes; o mesmo inventário produz projeção estável e sem caminhos; catálogo não expõe módulos/classes de carregamento. O mesmo problema foi observado no wheel instalado fora da fonte.

### O que a prova NÃO afirma

Não demonstra que um Nexus Server real escolheu o binário errado: os outros aplicativos não foram executados. Mostra que o contrato atual não fornece informação suficiente para distinguir as opções. Não exige que cópias do mesmo build tenham hashes de conteúdo diferentes. Ao contrário, manter a mesma identidade de build é correto; o que falta é a identidade da instalação local.

### Direção da correção

Separar explicitamente **tipo de runtime**, **identidade de build/conteúdo**, **instalação local selecionável** e **agente**. Publicar/resolver uma referência opaca da instalação no host produtor. Não alterar fingerprints usados por qualificações, hashes de intenção ou identidades de agentes para contornar o problema. Não escolher a primeira entrada nem usar posição no array. O plano C11 detalha opções aditivas e migração.

## Integração dos consumidores

Os aplicativos podem consumir catálogo e avaliação agora, sem listas de runtimes e sem copiar regras de qualificação. A avaliação é executada no host que contém o runtime; o Server adiciona política do agente, conectividade, TTL e revisão do inventário. A UI apresenta a projeção recebida.

Antes de aceitar binding para uma instalação entre opções equivalentes, completar A11-01. Enquanto isso, um fluxo de integração controlado com uma única instalação inequívoca por adaptador pode avançar; uma lista ambígua não deve escolher silenciosamente por ordem. A fonte dos adaptadores continua no Core; referência local não é nova identidade canônica.

## Reprodução

`python executar_verificacao.py --repo /caminho/do/core --output /caminho/das/evidencias`

O runner inclui as cinco verificações atuais e as sementes C10/C9 originais, além dos testes C9 disponíveis no repositório. Não instala dependências nem altera a fonte. Os testes novos são expectativas corretas, não patches. O código do produto não foi modificado.

As dependências foram isoladas: RFC8785 0.1.4 recuperado da fonte oficial por conector e conferido pelos hashes Git do upstream, sem stub; jsonschema 4.26.0 e pytest 9.0.2. A primeira tentativa de pip não conseguiu acessar DNS. O build final utilizou o backend setuptools instalado, sem isolamento online. `evidencias/` preserva comandos, XMLs, logs e hashes de artefatos. Erros preliminares de montagem de fixture/formato de hash não foram contabilizados como achados.
