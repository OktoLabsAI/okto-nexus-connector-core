# Release decision — correção C1 (2026-09-26)

**Nível alcançado: E1 — Core corrigido em escopo delimitado.**
E0 também está disponível (contratos/factory públicos com pin exato).
E2 e E3 **não** são declarados: dependem dos hosts N/C (não iniciados),
do substrato attach qualificado e de campanhas de SO/provedor
adicionais. Nenhuma publicação PyPI foi executada.

## Escopo E1 comprovado

- **Defeitos F01–F07 corrigidos** com as nove sementes da auditoria
  verdes (`tests/regression/test_c1_regressions.py` 9/9).
- **Lacunas G01–G05 tratadas**: factory pública (`create_runtime`),
  identidade portável de build separada do binding local, discovery
  passiva de layouts (releases Pi + shims npm) sem executar wrappers,
  tipos públicos de attach com recusa prescritiva, preflight de
  contenção tipado antes de qualquer spawn.
- **G06**: matriz RC atualizada com evidência por linha; PASS somente
  com execução real; BLOCKED registrado com dono/requisito.

## Artefato

- Distribuição `nexus-connector-core 0.2.0.dev0` (desenvolvimento).
- Wheel SHA-256
  `633483707aaf7eb7cfebdfee53f57e99ace45ae657017bf4a3dfa91783d8e253`;
  sdist SHA-256
  `a73d495411acf4bbeed1a2bf1dfe1e545d7e6399da506fd07ca8d4baa6bb88ba`.
  Builds normalizados byte-idênticos Windows/WSL2. Twine estrito,
  validador de release (modo desenvolvimento, `publishable:false`) e
  instalação offline com os dois smokes de consumidor passaram.

## Suítes (PYTHONPATH=src)

| Ambiente | Resultado |
|---|---|
| Windows / Python 3.13 (sistema) | 697 passed, 74 skipped, 2 warnings |
| WSL2 / Python 3.13 | 753 passed, 18 skipped |
| WSL2 / Python 3.11 (dedicado) | 753 passed, 18 skipped |
| WSL2 / Python 3.12 (dedicado) | 753 passed, 18 skipped |
| Windows / Python 3.11, 3.12 e 3.13 (com PYTHONPATH absoluto) | 697 passed, 74 skipped cada |

## Bloqueios para E2/E3 (com dono)

1. **Hosts N/C** (planos não iniciados): RC-13-01/02/04/05/09/12,
   J01–J34, TK-43.
2. **Attach real**: RC-12-01/02/06 (substrato qualificado + hosts).
3. **CI hospedada**: billing do GitHub (persiste).
4. **Windows logoff assistido**: procedimento preparado (RC-11-09 Linux já executado).
5. **PyPI**: sessão conjunta com o usuário (excluída do escopo C1).
6. **Provedores adicionais/plataformas**: fora da matriz qualificada
   registrada em `docs/compatibility.md`.

## Compatibilidade/migração

- Armazenamento SQLite inalterado; journals dev0 reabrem com histórico
  íntegro (ensaio RC-14-01/02). IDs novos limitados a 1–160; legado
  161–256 legível via `legacy_operation_receipt`. `reconcile` agora
  levanta `CoreError(VALIDATION_ERROR)` (era `ValueError` — hosts devem
  ajustar). `close()` síncrono do journal é ponte transitional;
  prefira `aclose()`.


## Adendo C2 (2026-09-27) — reavaliação independente de `e6b6305`

A reauditoria (`FIX_UPDATE_PLAN/`) confirmou 10 achados (R01–R10, 14
sementes) e **rejeitou E1** para `0.2.0.dev0`. A correção C2 foi
executada na ordem do §7: todas as 14 sementes verdes com invariantes
preservadas; suítes completas em 6 ambientes (Windows e WSL2 × 3.11–3.13:
713/74 e 768/19); matriz §5.2 requalificada linha a linha; artefato
normalizado **0.2.1.dev0** byte-idêntico Windows↔WSL2 (wheel
`sha256:d0c35f4cd386ae35ac2bc8c143c9c6b18a11ab0d61dd39bcc8bf60290ebfa538`,
sdist `sha256:e7b386eb0209e57acb5b64168b92367ba15eeceeccb76ce0ea516e0bacd74ff2`),
twine/offline/smokes verdes, **não publicado**. Evidência:
`plans/correction-c2/evidence/R01-R10.md`.

**E1 declarado para 0.2.1.dev0** segundo os critérios §8: nenhuma semente
apagada/trocada/xfailada; nenhuma gate de contenção removida para ficar
verde; unknown conservador segue válido; sem promessa exactly-once. E2/E3
continuam bloqueados pelos mesmos donos externos (hosts N/C, attach,
billing, PyPI conjunta).


## Adendo C3 (2026-09-27) — reavaliação independente de `7a7a248`

Segunda reauditoria (`FIX_UPDATE_PLAN/`): 8 achados (S01–S08, 11
sementes), **E1 rejeitado para 0.2.1.dev0**. Correção C3 executada
(A00–A08): 11 sementes + 2 guardas de recuperação verdes; 14 sementes
C2 preservadas; inventário automático confirma zero awaits de I/O sob o
lock global; suítes em 6 ambientes (Windows/WSL2 × 3.11–3.13: 726/74 e
781/19); artefato normalizado **0.2.2.dev0** byte-idêntico (wheel
`sha256:08b2fe7f…551a1d98`, sdist `sha256:e76014c4…fddb87d7`), twine/
offline verdes, **não publicado**. Pi requalificado sob o algoritmo v2
(`sha256:bc3b22f8…4284914`). Evidência: `plans/correction-c3/evidence/
S01-S08.md`. **E1 declarado para 0.2.2.dev0**; E2/E3 seguem bloqueados
pelos hosts reais (N/C), backend Linux compatível para campanha de
backend, attach, billing e PyPI conjunta.


## Adendo C4 (2026-09-28) — reavaliação independente de `8677145`

Terceira reauditoria (`FIX_UPDATE_PLAN/`): 7 achados (T01–T07, 10
sementes), **E1 rejeitado para 0.2.2.dev0**. Correção C4 executada
(C4-00..C4-07, 47 tarefas DONE em `plans/correction-c4/backlog.json`;
matriz C4T-01..53 em `matrix.json` — 52 PASS/mapeados, **C4T-52 BLOCKED**
dois hosts reais). 10/10 sementes verdes (baseline 10/10 fail registrado);
C2/C3 preservadas; cenários combinados em
`tests/regression/test_c4_complementary.py`; fronteiras em
`plans/correction-c4/EFFECT_BOUNDARIES.md`. Suítes: Windows 3.13/3.11/
3.12 = 742/74 cada; WSL2 3.13/3.11/3.12 = 797/19 cada. Artefato
normalizado **0.2.3.dev0** byte-idêntico (wheel
`sha256:12891135…f01dfe1`, sdist `sha256:4006f997…eda8d60`), twine/
offline verdes, **não publicado**. Pi requalificado sob
`core.build_identity.v3` (`sha256:caf8bfad…22de487b`). **E1 declarado
para 0.2.3.dev0**; E2/E3 seguem bloqueados (hosts N/C, attach, billing,
PyPI conjunta).


## Adendo C5 (2026-09-28) — reavaliação independente de `3d304f9`

Quarta reauditoria (`FIX_UPDATE_PLAN/`): 7 achados (U01–U07, 10 sementes
+ 1 controle positivo), **E1 rejeitado para 0.2.3.dev0**. Correção C5
executada (C5-00..C5-07, 48 tarefas DONE em
`plans/correction-c5/backlog.json`; matriz de aceite com 57 linhas
[56 planejadas + granularidade extra em C5-06] em `matriz_aceite.json`:
56 PASS, 1 NOT_RUN declarado — campanha de backend SO em host
qualificado). 10/10 sementes verdes + controle; baseline 10 FAIL + 1
PASS registrado; C2/C3/C4 preservadas (c4t13 reescrito conforme
C5-03.06; matriz C4 com delimitações explícitas). Suítes: Windows
3.13/3.11/3.12 = 753/74 cada; WSL2 3.13/3.11/3.12 = 807/19 cada.
Artefato normalizado **0.2.4.dev0** byte-idêntico (wheel
`sha256:d1a4d004…265cdb65`, sdist `sha256:ba555bd4…eda404b3`), twine/
offline verdes, **não publicado**. **E1 declarado para 0.2.4.dev0**;
E2/E3 seguem bloqueados (hosts N/C reais, attach, billing, PyPI
conjunta).
