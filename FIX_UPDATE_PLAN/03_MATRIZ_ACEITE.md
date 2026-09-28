# Matriz de aceite C11

16 cenários; 2 FAIL, 4 PASS e 10 NOT_RUN no snapshot auditado. Dois FAIL demonstram um único achado. Repetições e testes do wheel não são cenários independentes. NOT_RUN descreve requisitos de correção/integração, não defeitos adicionais comprovados.

## AC11-01 — Codex: duas cópias idênticas

**Estado:** FAIL. **Camada:** unit/public-discovery.

**Preparação:** Dois diretórios confiáveis com codex byte-idêntico.

**Ação:** Descobrir e projetar pela API pública.

**Resultado exigido:** Duas refs diferentes para os dois alvos, build_identity igual.

**Evidência:** test_distinct_identical_installations_have_unambiguous_public_refs[codex_app_server-codex]

## AC11-02 — Claude: duas cópias idênticas

**Estado:** FAIL. **Camada:** unit/public-discovery.

**Preparação:** Dois diretórios confiáveis com claude byte-idêntico.

**Ação:** Descobrir e projetar pela API pública.

**Resultado exigido:** Duas refs diferentes para os dois alvos, build_identity igual.

**Evidência:** test_distinct_identical_installations_have_unambiguous_public_refs[claude_stream-claude]

## AC11-03 — Builds diferentes continuam distintos

**Estado:** PASS. **Camada:** unit/public-discovery.

**Preparação:** Dois binários de laboratório com bytes distintos.

**Ação:** Descobrir e avaliar.

**Resultado exigido:** Referências diferentes; nenhum spawn.

**Evidência:** test_control_distinct_builds_already_have_distinct_refs

## AC11-04 — Repetibilidade e projeção sem caminhos

**Estado:** PASS. **Camada:** unit/public-api.

**Preparação:** Mesmo inventário, sem versão qualificada.

**Ação:** Avaliar duas vezes e serializar.

**Resultado exigido:** Resultados iguais, nenhum caminho, nenhum READY indevido.

**Evidência:** test_control_repeat_of_same_inventory_is_stable_and_path_free

## AC11-05 — Catálogo seguro permanece

**Estado:** PASS. **Camada:** unit/public-api.

**Preparação:** Catálogo instalado.

**Ação:** Enumerar descritores.

**Resultado exigido:** IDs únicos, sem module/class_name públicos.

**Evidência:** test_control_catalog_has_no_private_loading_coordinates

## AC11-06 — Recuperação C10/C9 preservada

**Estado:** PASS. **Camada:** fault-injection.

**Preparação:** Sementes originais e peers de laboratório.

**Ação:** Rodar runner original completo.

**Resultado exigido:** 12 PASS como nesta revisão, com barreiras antes da assert.

**Evidência:** evidencias/original_c10/resultados.xml

## AC11-07 — Reordenação do inventário

**Estado:** NOT_RUN. **Camada:** unit.

**Preparação:** Mesmo conjunto de instalações em ordens opostas.

**Ação:** Projetar e resolver seleção A.

**Resultado exigido:** A continua A; ID não depende de posição.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-08 — Resolução exata A/B

**Estado:** NOT_RUN. **Camada:** contract/public-api.

**Preparação:** Duas refs após correção.

**Ação:** Resolver cada uma pelo helper/contrato público.

**Resultado exigido:** Candidato físico exato; zero resultado e ambiguidade geram erro tipado.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-09 — Aliases para o mesmo alvo

**Estado:** NOT_RUN. **Camada:** platform/contract.

**Preparação:** Duas entradas PATH/symlinks do mesmo alvo permitido.

**Ação:** Descobrir segundo política documentada.

**Resultado exigido:** Aliases seguem política consistente; nunca dois alvos distintos sob uma ref silenciosa.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-10 — Drift após a seleção

**Estado:** NOT_RUN. **Camada:** integration/fault.

**Preparação:** Selecionar candidato na revisão R e modificar bytes/layout.

**Ação:** Preparar com evidência antiga.

**Resultado exigido:** Recusa antes de efeito; sem nova qualificação implícita.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-11 — Migração da referência v1 ambígua

**Estado:** NOT_RUN. **Camada:** migration/contract.

**Preparação:** Ref legada fingerprint casa com duas instalações.

**Ação:** Migrar/consumir referência antiga.

**Resultado exigido:** Resseleção exigida; nenhuma escolha por ordem. Caso único tem migração testada.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-12 — Formato incompatível

**Estado:** NOT_RUN. **Camada:** contract.

**Preparação:** Consumidor suporta formato diferente.

**Ação:** Ler projeção com versão desconhecida.

**Resultado exigido:** Estado incompatível ou recusa explícita; não binding silencioso.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-13 — Escopo de dois executores

**Estado:** NOT_RUN. **Camada:** consumer-contract.

**Preparação:** Duas instalações com caminhos semelhantes em hosts distintos.

**Ação:** Selecionar com executor/revisão incorretos.

**Resultado exigido:** Não resolver em outro inventário; catálogo não outorga autoridade.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-14 — UI orientada por dados

**Estado:** NOT_RUN. **Camada:** Nexus-Server UI.

**Preparação:** Fixture pública com refs distintas e mesmo label.

**Ação:** Renderizar e selecionar ambas.

**Resultado exigido:** Sem enum próprio e sem colapso por display_name/build. Este teste pertence ao Server.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-15 — Estados independentes do ambiente unitário

**Estado:** NOT_RUN. **Camada:** unit.

**Preparação:** Preflight controlado positivo/negativo por teste; build policy controlada.

**Ação:** Verificar precedência de estados; manter teste real separado.

**Resultado exigido:** READY somente no positivo qualificado; não desativar gate de produto.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.

## AC11-16 — Wheel revisado resolve identidade publicamente

**Estado:** NOT_RUN. **Camada:** artifact/consumer.

**Preparação:** Instalar novo wheel fora da fonte.

**Ação:** Enumerar, descobrir, avaliar e resolver A/B sem private imports.

**Resultado exigido:** Mesmo contrato nos consumidores sintéticos; não alegar E2 real.

**Evidência:** A implementar/executar; anexar test node, comando e resultado.
