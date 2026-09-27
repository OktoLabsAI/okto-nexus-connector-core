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
| Windows / uv 3.11-3.12 (venvs improvisados) | falhas de timing/crash-peer documentadas como limitação do ambiente (não regressão; ver evidência PC12-PC14) |

## Bloqueios para E2/E3 (com dono)

1. **Hosts N/C** (planos não iniciados): RC-13-01/02/04/05/09/12,
   J01–J34, TK-43.
2. **Attach real**: RC-12-01/02/06 (substrato qualificado + hosts).
3. **Campanha de logout/sessão de SO**: RC-11-09.
4. **CI hospedada**: billing do GitHub (persiste).
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
