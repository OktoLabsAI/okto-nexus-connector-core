# Validação de 0.2.8.dev0 — catálogo público e recuperação C9

**Entrada:** `okto-nexus-connector-core-main(7).zip`.  
**Commit no comentário do ZIP:** `c5bd9557861f44577ae8dbf5585790acfd045fa5`.  
**Versão:** `0.2.8.dev0`, coerente entre pyproject e export do pacote.  
**Baseline anterior:** `6a43e90a787f3a87af8e26f3f93d4c708cf8a0a8`, `0.2.7.dev0`.  
**Data da revisão e dos testes locais:** 28/09/2026.

## 1. Veredito

O catálogo público está entregue e é utilizável pelos consumidores. Nexus Server e Connector podem desenvolver sua integração sem arrays autoritativos de runtimes e sem copiar adaptadores. O wheel instalado fornece RuntimeCatalog/RuntimeDescriptor/get_runtime_catalog e discovery sem enumerar IDs no chamador.

Restam dois pontos, não uma nova lista extensa de problemas:

1. **Z01 — Disponibilidade técnica por instalação ainda não publicada.** É a parte C9-01.4 do contrato de binding, não um defeito no catálogo de tipos conhecidos. A implementação pública continua devolvendo candidatos locais, sem avaliação de qualificação/plataforma/contenção e razões técnicas prontas para consumo. Precisa ser concluída para a UI habilitar bindings sem duplicar regras internas do Core.
2. **Z02 — O timeout de shutdown ainda cancela o produtor de liberação durável.** A alteração protege o collector localmente, mas coloca o produtor em outro gather que o cancela. Isso pode prolongar o shutdown quando o cancelamento do backend precisa terminar sua limpeza. Prioridade P2; duas reproduções independentes repetidas.

A auditoria não reproduziu novo P1 nos caminhos verificados. Isso não é certificação universal nem aceite operacional de recuperação: Z02 e a avaliação de disponibilidade precisam ser concluídos no escopo pertinente. As combinações de provider/SO e a integração real dos aplicativos continuam requerendo suas próprias campanhas.

## 2. Método e evidência

Extraí o ZIP separadamente, comparei os arquivos alterados com o snapshot anterior e preservei hashes dos 403 arquivos originais. Usei Python 3.13 em ambiente de revisão, pytest 9.0.2 e jsonschema 4.26.0. O pip não teve acesso de rede para obter rfc8785; foram obtidos os dois módulos upstream da tag v0.1.4 pelo conector GitHub. Seus bytes foram verificados pelos hashes Git de blob oficiais:

- `_impl.py`: `3137d3326b98938affadb1be711ee411eb2ab86e`.
- `__init__.py`: `5a1f9d919643fa3bcaa0999ea66d9c535568c42a`.

Não utilizei um stub de canonicalização. A proveniência completa está em evidencias/rfc_provenance.json. Erros iniciais de ambiente/assinatura no script de verificação instalada foram corrigidos antes da campanha final e não foram classificados como defeitos do produto.

| Campanha | Resultado local |
|---|---|
| C9 do executor, catálogo + recuperação | 7 PASS |
| Sementes originais C9 | 2 PASS |
| Histórico C2–C8 do repositório | 75 PASS, 1 SKIP, 1 warning |
| Novas verificações | 2 FAIL, 1 controle PASS |
| Repetição das novas verificações | 2 FAIL, 1 controle PASS |
| Runner distribuído, incluindo os 12 casos | 2 FAIL, 10 PASS |
| Suíte completa | 711 PASS, 123 FAIL, 20 SKIP, 2 warnings |
| Wheel/sdist, instalação e consumidores sintéticos | PASS |
| Consulta instalada do catálogo, sem spawn/journal/porta | PASS |
| Regeneração dos contratos em cópia da fonte | PASS, bytes idênticos |

Não somar subconjuntos e repetições à suíte. Os XMLs, logs, comandos e resumo JSON estão em evidencias/.

As 123 falhas da suíte completa foram inspecionadas e agrupadas: 86 recusas de capacidade após árvores não comprovadamente encerradas; 24 probes sem comprovação de parada; 9 recusas diretas relacionadas a proc_children; 2 divergências de mensagem consequentes; 1 teste de morte do proprietário e 1 assert de preflight. O ambiente não possui `/proc/self/task/<pid>/children`. Não são 123 bugs independentes. Nenhum gate foi removido. Os dois testes Z02 não dependem do guardian ou desses erros.

O warning histórico vem de uma fixture `_ClockLateNative.close` assíncrona utilizada em um caminho que espera função síncrona. Não o tratei como novo erro de provider. Datas e resultados Windows/WSL2 apresentados pelo executor são evidência recebida, não reproduzida pelo revisor.

## 3. Catálogo: parte validada

### 3.1. Contrato público

`catalog.py:59–134` publica DTOs congelados e uma consulta que projeta `adapter_specs()` do registro. Há versão do formato e versão do Core, nomes de exibição, família, modo, plataformas de implementação e estado de suporte. Módulos/classes de carregamento não são expostos.

O consumidor instalado enumerou:

| adapter_id | display_name | modo | suporte declarado |
|---|---|---|---|
| codex_app_server | Codex (app-server) | managed | managed_supported |
| pi_rpc | Pi (Node RPC) | managed | managed_supported |
| claude_stream | Claude Code (stream) | managed | managed_supported |
| claude_attach | Claude Code (attach) | attach | registered_unqualified |

Attach continua não descobrível e não é apresentado como READY. Plataformas de implementação não são qualificação de todos os backends.

A verificação isolada interceptou eventos de spawn, conexão SQLite e bind de socket durante a consulta: nenhum ocorreu. Não houve carregamento dos módulos dos adaptadores dos providers. O pacote foi importado de uma instalação do wheel fora da árvore-fonte.

### 3.2. Fonte de IDs e discovery

`contracts/generate.py:10–20` agora deriva ADAPTER_IDS do registry. Executei a geração em uma cópia do snapshot e comparei os JSONs antes/depois: bytes idênticos. Isso resolve a segunda enumeração manual dos quatro IDs no gerador.

`DiscoveryRequest.adapter_ids=None` passa a significar todos os descobríveis do catálogo, e `()` continua sendo filtro vazio. O caminho explícito de IDs foi preservado. A implementação de discovery permanece dentro do Core.

Código disponível hoje:

```python
from nexus_connector_core import get_runtime_catalog, DiscoveryRequest

catalog = get_runtime_catalog()
for descriptor in catalog.runtimes:
    print(descriptor.adapter_id, descriptor.display_name,
          descriptor.support_status)

# Em um host que já compôs seu RuntimeCore:
# inventory = await runtime.discover(DiscoveryRequest())
```

Não criar arrays de runtimes nos aplicativos. Eles podem mapear esses descritores para uma API de apresentação, preservando IDs e versão.

## 4. Z01 — Falta a avaliação pública de disponibilidade

**Natureza:** lacuna funcional do C9-01.4; bloqueia o aceite do seletor completo, não o início de seu desenvolvimento.

`models.py:202–250` ainda define InstallationCandidate apenas com adapter, caminhos/fingerprint, source/trust, versão, arquitetura, script e build_identity. Inventory contém somente a tupla de candidatos. `RuntimeCore` não publica avaliação de disponibilidade. `inventory_reducer.py` possui uma projeção de candidatos para rede, mas sem as dimensões de prontidão/qualificação.

Consequência: um consumidor sabe quais tipos existem e quais arquivos foram encontrados. Ainda não consegue perguntar publicamente quais candidatos estão tecnicamente prontos e por quê, sem interpretar regras que pertencem ao Core. Usar `managed_supported` ou `trust=selected` como READY seria incorreto.

O requisito já estava em C9-01.4: projeção tipada por candidato, confiança, qualificação, contenção, preparação e capacidades efetivas; sem login ou spawn implícito. C9-01.6 destina ao Server somente a decisão canônica de binding e a projeção do executor correto.

A correção deve reaproveitar as políticas atuais do Core, não outra allowlist. Precisa diferenciar estado técnico de autorização do agente, instalação local de executor remoto e tipos conhecidos de candidatos concretos. Dois builds da mesma família não podem ser fundidos pelo nome. Ausência de probe deve permanecer inconclusiva.

**Evidência:** inspeção da superfície/DTO/port e inventário emitido pelo wheel, em evidencias/catalog_observation.json. Não foi criado teste que falha simplesmente porque uma função com nome escolhido pelo revisor não existe.

## 5. Z02 — O produtor ainda é cancelado pelo gather de cleanup

**Prioridade:** P2, continuação de C9-03.1–03.4.

### 5.1. Causa no código

`_schedule_release_retries()` guarda o task em `obligation.retry_task`, mas também o adiciona a `_cleanup_tasks` (`runtime.py:1919–1925`). O shutdown aguarda esse conjunto via `wait_for(gather(...), cleanup_budget+1)` em dois pontos (`runtime.py:1182–1188` e `1200–1206`). O timeout cancela o gather e o produtor incluído nele.

O shield em `_retry_release_obligations()` cobre o collector daquela chamada, não o mesmo produtor aguardado por outro gather. A propriedade do commit ainda não está separada da espera cancelável.

### 5.2. Reprodução: produtor cancelado

O teste cria uma abertura cancelada com retorno tardio, comprova STOPPED e falha uma vez no release antes do commit, para criar a obrigação. A liberação seguinte fica aguardando uma barreira de armazenamento. O shutdown público esgota seu orçamento.

Observado: a obrigação permanece, mas seu `retry_task` está cancelado e o backend recebeu CancelledError. Isso contraria a semântica de conservar o produtor e terminar apenas a espera. A retomada pode exigir outro release em vez de colher o resultado original.

Não demonstrei corrupção ou perda de reserva persistida. O problema confirmado é o cancelamento de uma operação que a biblioteca afirma continuar supervisionando.

**Teste:** `test_shutdown_deadline_does_not_cancel_owned_release_producer`.

### 5.3. Reprodução: retorno preso na limpeza do cancelamento

O mesmo port de ledger aguarda uma operação, recebe cancelamento e precisa aguardar sua finalização para encerrar. Com `ShutdownPolicy(0,0)` e cleanup de 0,03 s, o shutdown permaneceu pendente após 3,5 s enquanto a barreira continuava fechada. A chamada estava aguardando o gather do cleanup, não a execução de um provider.

A barreira é liberada somente no teardown, e a liberação real depois converge. Esse é um backend de laboratório que representa uma limpeza de operação em andamento; o SQLiteJournal e o lifecycle do Core são reais. Não é uma alegação de que a transação SQLite normal sempre demora a cancelar.

**Teste:** `test_shutdown_return_does_not_wait_for_release_cancel_cleanup`.

### 5.4. Controle que passou

O teste de duas chamadas públicas de shutdown após a primeira força falhar manteve pico de uma força ativa e não duplicou a tentativa nesse cenário. Esse controle foi repetido. Não foi classificado como achado adicional.

**Teste:** `test_concurrent_shutdown_retry_coalesces_the_current_force_producer`.

## 6. Integração recomendada

A divisão permanece:

| Camada | Responsabilidade |
|---|---|
| Core | Adaptadores, catálogo, discovery, avaliação técnica, lifecycle e contratos |
| Connector | Consultar o Core do host remoto, gerir identidade/bindings locais e transmitir projeção |
| Server | Core embutido local; inventário remoto por executor; políticas do agente; API da UI |
| UI | Renderizar descritores/estados recebidos; nunca lista autoritativa de runtimes |

Desenvolver os aplicativos agora. O catálogo atual já permite retirar listas duplicadas de tipos. Concluir Z01 antes de declarar a seleção de instalações prontas implementada; concluir Z02 antes de aceitar a garantia de shutdown/recuperação sob falha correspondente. Não contornar nada nos consumidores acessando internals.

## 7. Artefatos e limites de aceite

Construí wheel/sdist em cópia da fonte usando o backend setuptools disponível; não alterei o snapshot. A instalação do wheel e os consumers `embedded`/`remote` passaram no mesmo artefato. O bundle foi validado com aceitação explícita de `development-partial`, hash `sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630`.

Os hashes desta construção estão em evidencias/package_validation.json. Não devem ser confundidos com os hashes de uma construção normalizada do executor; eu não reproduzi aquela campanha de normalização.

Não executei providers reais, campanhas Windows/WSL2 nem Server e Connector em dois hosts. Os examples isolados são smokes sintéticos de consumo da biblioteca, não E2.

**Nenhuma correção foi aplicada ao produto.** O plano C10 anexo é restrito aos dois pontos pendentes, preservando todo o trabalho que passou.
