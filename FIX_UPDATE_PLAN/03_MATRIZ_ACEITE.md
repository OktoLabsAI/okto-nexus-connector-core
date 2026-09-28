# Matriz C10 — estados desta auditoria

20 cenários: 7 PASS, 2 FAIL, 10 NOT_RUN e 1 BLOCKED. NOT_RUN é uma verificação complementar, não outro defeito confirmado. PASS de metadados/smoke não comprova provider real.

## A01 — Catálogo público instalado

**Estado:** PASS.

**Resultado exigido:** Consulta no wheel sem spawn, journal ou bind; DTOs sem módulo/classe.

**Evidência/referência:** `evidencias/catalog_observation.json`.

## A02 — Fonte única para schemas

**Estado:** PASS.

**Resultado exigido:** Gerar contratos em cópia e comprovar bytes iguais.

**Evidência/referência:** `evidencias/generation.json`.

## A03 — Discovery padrão e attach

**Estado:** PASS.

**Resultado exigido:** 7 casos C9 do executor passam; None pergunta catálogo, attach não elegível por existir.

**Evidência/referência:** `evidencias/c9_delivered.xml`.

## A04 — Recuperação Y01/Y02 original

**Estado:** PASS.

**Resultado exigido:** As duas sementes anteriores passam sem alteração.

**Evidência/referência:** `evidencias/c9_original.xml`.

## A05 — Produtor durável não cancelado

**Estado:** FAIL.

**Resultado exigido:** Com ledger retido, orçamento do shutdown não cancela obligation.retry_task.

**Evidência/referência:** `test_shutdown_deadline_does_not_cancel_owned_release_producer`.

## A06 — Prazo não depende da limpeza de cancelamento

**Estado:** FAIL.

**Resultado exigido:** Backend demora a cancelar; waiter público retorna sem liberar a barreira.

**Evidência/referência:** `test_shutdown_return_does_not_wait_for_release_cancel_cleanup`.

## A07 — Controle de força concorrente

**Estado:** PASS.

**Resultado exigido:** Duas chamadas públicas; pico de uma tentativa ativa no mesmo recurso.

**Evidência/referência:** `test_concurrent_shutdown_retry_coalesces_the_current_force_producer`.

## A08 — Disponibilidade por API pública

**Estado:** NOT_RUN.

**Resultado exigido:** Wheel avalia candidato sem importar regra privada; sem login/spawn implícito.

**Evidência/referência:** `Complementar C10-01.1`.

## A09 — Build desconhecido não vira READY

**Estado:** NOT_RUN.

**Resultado exigido:** Instalação presente e confiável, versão ou conteúdo não qualificado: motivo explícito.

**Evidência/referência:** `Complementar C10-01.2`.

## A10 — Plataforma e contenção

**Estado:** NOT_RUN.

**Resultado exigido:** Host incompatível/sem backend retorna estado restritivo; registrado não significa pronto.

**Evidência/referência:** `Complementar C10-01.2`.

## A11 — Dois candidatos da mesma família

**Estado:** NOT_RUN.

**Resultado exigido:** IDs e avaliações distintos; sem seleção por display_name nem colapso de versões.

**Evidência/referência:** `Complementar C10-01.3`.

## A12 — Projeção remota segura

**Estado:** NOT_RUN.

**Resultado exigido:** Versão/schema explícitos, sem paths/segredos/classes; Server usa fatos do executor remoto.

**Evidência/referência:** `Complementar C10-01.3/01.4`.

## A13 — Cancelamento externo e release

**Estado:** NOT_RUN.

**Resultado exigido:** Cliente cancela shutdown; produtor continua possuído e commit tardio converge.

**Evidência/referência:** `Complementar C10-02.1/02.2`.

## A14 — Release concluído antes da nova chamada

**Estado:** NOT_RUN.

**Resultado exigido:** Colher sucesso antes de agendar retry; nenhuma segunda liberação dispensável.

**Evidência/referência:** `Complementar C10-02.3`.

## A15 — ACK perdido e retry coalescido

**Estado:** NOT_RUN.

**Resultado exigido:** Commit seguido de erro; consulta/idempotência fecha mesma obrigação sem inferir rollback.

**Evidência/referência:** `Complementar C10-02.3`.

## A16 — Ledger retido e outro recurso vivo

**Estado:** NOT_RUN.

**Resultado exigido:** Força independente da obrigação durável; relatório mantém ambas causalidades.

**Evidência/referência:** `Complementar C10-02.4`.

## A17 — Histórico C2–C8

**Estado:** PASS.

**Resultado exigido:** 75 passaram, 1 skip; não somar subconjunto à suíte completa.

**Evidência/referência:** `evidencias/history_c2_c8.xml`.

## A18 — Artefato e consumers isolados

**Estado:** PASS.

**Resultado exigido:** Wheel/sdist, bundle development-partial explícito, mesmo wheel em dois smokes sintéticos.

**Evidência/referência:** `evidencias/package_validation.json`.

## A19 — Qualificação real de backend/provider

**Estado:** BLOCKED.

**Resultado exigido:** Campanha do SO com contenção efetiva; sem converter o sandbox ou XML recebido em prova local.

**Evidência/referência:** `Ambiente sem proc_children; provider real não executado`.

## A20 — UI real e integração de hosts

**Estado:** NOT_RUN.

**Resultado exigido:** Server+Core local e Server–Connector real em dois hosts; habilitação deriva de avaliação+política.

**Evidência/referência:** `Pertence aos aplicativos, não substituído por smoke`.

