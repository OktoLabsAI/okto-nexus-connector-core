# PENDÊNCIAS — okto-nexus-connector-core (pós-correção C1, 2026-09-26/27)

Estado de entrega: **E1** (Core corrigido em escopo delimitado; C2
concluída). Artefato `0.2.1.dev0` (wheel `d0c35f4c…ebfa538`, sdist
`e7b386eb…ac74ff2`), byte-idêntico Windows/WSL2, não publicado. C1:
`15772d3`; reauditoria: `e6b6305`; correção C2: ver `git log`. Nenhuma pendência abaixo é executável dentro deste
repositório sem a ação do dono correspondente.

## A. Requer os projetos irmãos N (okto-nexus Server) e C (Connector) — não iniciados

| Item | O que falta | Desbloqueio |
|---|---|---|
| RC-13-01 | Core+Server local (runtime gerenciado pela API pública dentro do Server) | Início do plano N |
| RC-13-02 | Core+Connector remoto em dois hosts (mesmo wheel/hash nos dois) | Planos N+C; hosts distintos autorizados |
| RC-13-04 | MCP HTTP real: tráfego harness→Server observado | Plano N (endpoint MCP) |
| RC-13-05 | Tools-only sem Connector (harness independente + MCP HTTP) | Plano N + harness com MCP HTTP |
| RC-13-09 | Queda/reconexão de canal (WSS/NXL pertence aos hosts) | Planos N+C |
| RC-13-12 | Consumo exclusivo/handoff (domínio canônico do Server) | Plano N |
| RC-12-01 | Seleção de alvo attach na UI dos hosts (tipos Core prontos) | Planos N/C |
| TK-43 | Dois consumidores reais com o mesmo wheel | Planos N+C |
| J01–J34 | Campanha conjunta (N12+C10+K11 → N13/C11) | Planos N+C concluídos até seus gates |
| Bundle NXL normativo (TK-07) | Re-pin dos consumidores ao sair de `development-partial` | Consumidores integrando (N/C) |
| TK-44 | Compatibilidade atual/anterior | Exige um release anterior publicado |
| E2 / E3 | Gates de integração local+remota / escopo R3 completo | Tudo acima |

**Handoff pronto**: `plans/correction-c1/HANDOFF_ARTEFATO.md` (factory
`create_runtime`, breaking changes, callbacks, erros novos).

## B. Requer ambiente/substrato autorizado específico

| Item | O que falta | Desbloqueio |
|---|---|---|
| RC-12-02 | Revalidação TOCTOU do alvo attach | Substrato attach qualificado (attach é POSIX; sem Claude nativo Linux nesta máquina) |
| RC-12-06 | Eventos/correlação reais do substrato attach | Idem |
| Attach real (K08/E3) | Qualificação ATTACH_QUALIFIED | Idem; tipos `AttachTarget`/`AttachPolicy` públicos; sem flag |
| Windows logoff assistido | Logoff real encerra a sessão do próprio agente | Procedimento preparado (RC-11-09 Linux já PASS com `wsl --terminate`; script `tools/rc1109_owner.py`); executar com presença do usuário e conferir no re-login |
| Providers/plataformas fora da matriz | Ex.: provedores em Linux nativo, macOS, builds não qualificados | Ambientes autorizados; matriz em `docs/compatibility.md` |

## C. Requer ação do usuário

| Item | Ação |
|---|---|
| CI hospedada (TK-42) + workflow de release | Corrigir billing do GitHub ("recent account payments have failed or your spending limit needs to be increased") |
| Publicação PyPI (TK-45) | Sessão conjunta já preparada (runbook em `release_decision.md`/histórico): versão estável, revisão legal, environment `pypi` + trusted publisher, secrets de aprovação, dispatch com hashes |
| Decisão N/C | Iniciar os planos irmãos para desbloquear a Seção A |

## D. Itens internos menores (não bloqueiam E1)

- Campanha de logout do Windows (lado B acima) quando houver janela
  assistida.
- `PLANO_CORRECAO/` (pacote original de entrega do usuário) agora
  preservado no repositório como referência imutável; a campanha
  executável vive em `plans/correction-c1/`.
- O arquivo `=1` (pré-existente, não rastreado) permanece **preservado e
  fora de commits**, conforme instrução permanente.

## Atualização C10 (2026-09-30) — 0.2.9.dev0

- **Z02 corrigido**: o produtor de liberação durável não é mais membro
  do gather cancelável do shutdown; a rota de liberação de handle
  parado é ÚNICA (`_durable_release`) — espera sempre via shield;
  sucesso disponível é colhido antes de agendar; ACK perdido fecha a
  mesma obrigação; obrigações duráveis nunca atrasam contenção de
  outros recursos. Sementes do revisor verdes (A05/A06 + controle A07)
  + A13–A16.
- **Z01 entregue**: avaliação técnica pública por candidato
  (`evaluate_runtime_availability`) — o contrato de binding está
  completo para os hosts; fixture e critérios de UI no exemplo
  (`examples/availability_projection.py --json`).
- E1 re-declarado para **0.2.9.dev0** (adendo C10 em
  `release_decision.md`). E2/E3 seguem bloqueados externamente (hosts
  reais / providers reais / duas máquinas) — A19 BLOCKED, A20 NOT_RUN
  na matriz C10 (`plans/correction-c10/matriz_aceite.json`).
- Artefato byte-idêntico Windows↔WSL2 (wheel `sha256:cc56a693…bfc7d`),
  twine + offline verdes, **não publicado** (publicação PyPI segue
  exigindo sessão conjunta).

## Fontes de verdade

- Matriz RC: `plans/correction-c1/matriz_rc.md` (129 cenários: 120 PASS,
  9 BLOCKED — detalhe por linha).
- Backlog: `plans/correction-c1/BACKLOG_CORRECAO.json` (100 tarefas: 94
  DONE, 6 BLOCKED).
- Decisão de release: `plans/correction-c1/release_decision.md`.
- Relatório final: `plans/correction-c1/RELATORIO_FINAL_AGENTE.md`.
- Matriz TK/J original: `plans/implementation/matrix.md`.
