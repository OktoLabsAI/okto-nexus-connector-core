# RELATÓRIO FINAL DO AGENTE — Correção C1 do okto-nexus-connector-core

**Nível de entrega: E1** (Core corrigido em escopo delimitado; E0
disponível; E2/E3 explicitamente não declarados — ver
`release_decision.md`). Data: 26/09/2026. Base auditada: `706b16a`
(idêntica ao HEAD inicial; baseline em `baseline.json`).

## 1. Correções (F01–F07) — todas com semente verde

| Achado | Correção | Commits |
|---|---|---|
| F01 lease×send travado | fence de admissão em memória antes de I/O; coordenador único de fechamento; contenção física independente (`_independent_containment`) sem locks de send/journal; force nunca cancelado no bookkeeping | `435a40d` |
| F02 efeito após deadline | revalidação de lease pós-admit/pós-marker no kernel + `EffectFence` verificado no loop E na thread de despacho (ponto mais próximo do write) | `4c1270d` |
| F03 EOF aceitando trabalho | pump classifica exaustão/cancelamento via lifecycle; EOF inesperado cerca em memória antes do I/O e registra incidente único por epoch | `8efe8ee` |
| F04 SQLite no loop | `OffLoopExecutor`: worker dedicado por store, filas normal/urgente bornadas + orçamento de bytes, wake-tags (sem polling), entrega cancel-safe, `aclose`/`close` com prova; journal e slot-ledger 100% off-loop; replay paginado sem transação entre yields | `b945f85` |
| F05 IDs irrecuperáveis | política única 1–160 (= bundle NXL), recusas tipadas antes de efeito; `legacy_operation_receipt` leitura exata 161–256 sem replay | `e9f7984` |
| F06 retenção de sessões | evicção após stop observado + túmulos bornados (1024) preservando histórico honesto; ≤16 adapters retidos em 1000 ciclos | `5c2ea64` |
| F07 modelo ignorado | Codex: `thread_start_overrides.model` (contrato 0.157.0 verificado nos schemas); Claude: tokens `--model` estruturados; validação tipada | `6394ae9` |

## 2. Lacunas (G01–G06)

- **G01** factory pública `create_runtime` + Protocol completo +
  desacoplamento do journal concreto + exemplos/smokes sem imports
  privados (AST-testado) — `00aca84`.
- **G02** `build_identity` portátil (conteúdo, manifesto do pacote Pi
  inteiro) separada do `binding_fingerprint` path-bound; qualificação
  por identidade aditiva; drift duplo no prepare — `827562f`.
- **G03** `discover_pi_releases` passiva + parsing estrito de shims npm
  `.cmd` (hostil recusado sem execução) — `8cb706b`.
- **G04** `AttachTarget`/`AttachPolicy` públicos; attach falha
  prescritivo; ATTACH_QUALIFIED=False; RC-12-03/04/05/07 PASS, resto
  BLOCKED por substrato/hosts.
- **G05** `containment_preflight` passivo por requisito real (win32 job
  objects; linux procfs/children/pidfd/subreaper) ligado antes de
  segredos/spawn; `PROCESS_CONTAINMENT_UNAVAILABLE` tipado — `8cb706b`.
- **G06** matriz RC 129 linhas com evidência; PASS apenas com execução;
  BLOCKED com dono (hosts N/C, substrato attach, logout, billing,
  PyPI).

## 3. Execuções

- Suítes completas (todas com `PYTHONPATH=src`): Windows 3.13
  **697/74**; WSL2 3.13/3.11/3.12 dedicados **753/18 cada**. Venvs uv
  improvisados 3.11/3.12 no Windows: falhas de timing/crash-peer
  registradas como limitação de ambiente (evidência PC12-PC14).
- Campanhas reais de provider anteriores (autorizadas) permanecem
  válidas; nenhuma nova chamada de modelo foi feita na C1.
- Sementes dirigidas: **9/9 verdes**. Regression suites novas:
  offloop(8), containment(5), effect-guard(3), stream-loss(2),
  identifiers(17), composition(6), release(3), model(7),
  build-identity(6), discovery/preflight(7), migration(2).

## 4. Artefatos

- `nexus-connector-core 0.2.0.dev0`: wheel
  `63348370…3d8e253`, sdist `a73d4954…a6bb88ba`, byte-idênticos
  Windows/WSL2; twine estrito, offline installs + smokes OK; sem
  publicação remota.
- Handoff: `HANDOFF_ARTEFATO.md` (breaking changes: reconcile
  CoreError; journal `aclose`; `create_runtime`).
- Rastreabilidade: `BACKLOG_CORRECAO.json` (100 tarefas: 94 DONE, 6
  BLOCKED com dono), `matriz_rc.md` (129 RCs: 120 PASS, 9 BLOCKED — detalhe por
  linha na matriz), evidências por fase em
  `evidence/`.

## 5. Migração e riscos residuais

- Journals dev0 reabrem íntegros (ensaio RC-14-01/02); IDs longos
  legíveis; nada re-keyed. Schema de armazenamento inalterado.
- Riscos residuais: latência das travessias loop↔worker em janelas de
  teste muito curtas (documentado); attach/Pi-execução real/NXL
  normativo aguardam hosts; billing CI persiste; orçamento de bytes do
  executor é por instância de store.

## 6. Pendências por dono

- **Usuário**: billing GitHub; sessão PyPI conjunta; decisão de iniciar
  N/C; logoff assistido do Windows (procedimento preparado; lado Linux
  do RC-11-09 já executado e PASS).
- **Hosts N/C**: integração E2 (pin do wheel 0.2.0.dev0), campanhas J.
- **Core (futuro)**: attach qualificado; campaign logout/SO; bundle
  normativo quando consumidores fixarem revisão.
