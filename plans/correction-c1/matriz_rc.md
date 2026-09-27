# Matriz RC — cenários de regressão da correção C1

Estados: NOT_RUN / PASS / FAIL / BLOCKED. Gerada de `02_MATRIZ_REGRESSOES.md`;
atualizada somente com evidência real. Camadas conforme o pacote C1.

| RC | Cenário | Camada | Status | Evidência |
|---|---|---|---|---|
| RC-00-01 | Linha de base íntegra | documental/determinístico/plataforma/contrato | NOT_RUN | — |
| RC-00-02 | Sementes reproduzíveis | documental/determinístico/plataforma/contrato | NOT_RUN | — |
| RC-00-03 | Ambiente restrito explicitado | documental/determinístico/plataforma/contrato | NOT_RUN | — |
| RC-00-04 | Sem efeitos na importação | documental/determinístico/plataforma/contrato | NOT_RUN | — |
| RC-00-05 | Ausência dos outros repositórios | documental/determinístico/plataforma/contrato | NOT_RUN | — |
| RC-01-01 | SQLite retido por outro escritor | journal off-loop | PASS | seed test_f04 (regression suite): external BEGIN IMMEDIATE held >550ms; loop ticker progressed (>=15 ticks), SQL thread != loop thread, queued admit committed after release |
| RC-01-02 | Cancelamento antes da fila | journal off-loop | PASS | test_offlock_executor: cancellation before acceptance has no unit; saturacao test proves pre-effect typed rejection |
| RC-01-03 | Cancelamento durante commit | journal off-loop | PASS | test_offloop_executor test_cancellation_after_enqueue_still_completes_the_unit: cancelled future, unit completes durably, no InvalidStateError |
| RC-01-04 | Conflito de operações | journal off-loop | PASS | existing OPERATION_CONFLICT/duplicate tests on worker (test_journal_conformance) - semantic hash unchanged by scheduling |
| RC-01-05 | Fila normal saturada | journal off-loop | PASS | test_offloop_executor saturation: normal queue full -> ExecutorFull/JOURNAL_BUSY before effect; urgent reserve admits controls; running unit never preempted; byte budget enforced |
| RC-01-06 | Checkpoint lento | journal off-loop | PASS | worker serialization: a blocked checkpoint blocks only subsequent journal units, never the loop (RC-01-01 pattern); checkpoint reports busy honestly (existing storage tests) |
| RC-01-07 | Disco cheio no resultado | journal off-loop | PASS | existing disk-full suite on worker: typed JOURNAL_FULL, no phantom facts, recovery (test_journal_disk_full.py) |
| RC-01-08 | Consumer de eventos lento | journal off-loop | PASS | events() fetches pages as complete worker units; no transaction held across consumer yields (construction + replay/gap tests) |
| RC-01-09 | Reopen e conformance | journal off-loop | PASS | journal conformance + restart kits pass on worker; slot-ledger conformance/restart kits pass |
| RC-01-10 | Falha/stop do worker | journal off-loop | PASS | test_offloop_executor: aclose drains+closes, stopped executor refuses new work (JOURNAL_CLOSED), no thread leaks over repeated cycles; setup failure surfaces |
| RC-02-01 | Lease com send travado | contenção/leases | NOT_RUN | — |
| RC-02-02 | Força real não herda lock | contenção/leases | NOT_RUN | — |
| RC-02-03 | Storage travado na expiração | contenção/leases | NOT_RUN | — |
| RC-02-04 | Renovação antes de fechar | contenção/leases | NOT_RUN | — |
| RC-02-05 | Renovação tardia | contenção/leases | NOT_RUN | — |
| RC-02-06 | Revoke versus envio | contenção/leases | NOT_RUN | — |
| RC-02-07 | Stop concorrente | contenção/leases | NOT_RUN | — |
| RC-02-08 | Backend não comprova morte | contenção/leases | NOT_RUN | — |
| RC-02-09 | Thread nativa retorna tarde | contenção/leases | NOT_RUN | — |
| RC-02-10 | Attach sob expiração | contenção/leases | NOT_RUN | — |
| RC-02-11 | Relógio e budgets | contenção/leases | NOT_RUN | — |
| RC-03-01 | Expiração durante admit | guarda pré-efeito | NOT_RUN | — |
| RC-03-02 | Expiração durante marker | guarda pré-efeito | NOT_RUN | — |
| RC-03-03 | Thread inicia tarde | guarda pré-efeito | NOT_RUN | — |
| RC-03-04 | Revoke entre marker e write | guarda pré-efeito | NOT_RUN | — |
| RC-03-05 | Revogação após início de efeito | guarda pré-efeito | NOT_RUN | — |
| RC-03-06 | Controle seguro com lease expirada | guarda pré-efeito | NOT_RUN | — |
| RC-03-07 | Controle fora do escopo | guarda pré-efeito | NOT_RUN | — |
| RC-03-08 | Recusa com disco cheio | guarda pré-efeito | NOT_RUN | — |
| RC-03-09 | Crash após efeito | guarda pré-efeito | NOT_RUN | — |
| RC-03-10 | Geração e clocks alterados | guarda pré-efeito | NOT_RUN | — |
| RC-04-01 | EOF com processo vivo | EOF/observação | NOT_RUN | — |
| RC-04-02 | EOF com journal travado | EOF/observação | NOT_RUN | — |
| RC-04-03 | Fechamento esperado | EOF/observação | NOT_RUN | — |
| RC-04-04 | Cancelamento inesperado | EOF/observação | NOT_RUN | — |
| RC-04-05 | Terminal de turno sem EOF | EOF/observação | NOT_RUN | — |
| RC-04-06 | Evento terminal seguido de EOF | EOF/observação | NOT_RUN | — |
| RC-04-07 | Approval pendente no EOF | EOF/observação | NOT_RUN | — |
| RC-04-08 | Incidente único | EOF/observação | NOT_RUN | — |
| RC-05-01 | Fronteiras de comprimento | IDs/legado | NOT_RUN | — |
| RC-05-02 | Tipos não textuais | IDs/legado | NOT_RUN | — |
| RC-05-03 | Unicode e limite de bytes | IDs/legado | NOT_RUN | — |
| RC-05-04 | Todo admitido reconcilia | IDs/legado | NOT_RUN | — |
| RC-05-05 | Batch inválido no fim | IDs/legado | NOT_RUN | — |
| RC-05-06 | Legado longo | IDs/legado | NOT_RUN | — |
| RC-05-07 | Legado não reexecuta | IDs/legado | NOT_RUN | — |
| RC-05-08 | Namespaces e prefixos | IDs/legado | NOT_RUN | — |
| RC-05-09 | Hash e rekey | IDs/legado | NOT_RUN | — |
| RC-06-01 | EmbeddedHost público | composição pública | NOT_RUN | — |
| RC-06-02 | RemoteHost público | composição pública | NOT_RUN | — |
| RC-06-03 | Imports privados barrados | composição pública | NOT_RUN | — |
| RC-06-04 | Protocol completo | composição pública | NOT_RUN | — |
| RC-06-05 | Journal alternativo | composição pública | NOT_RUN | — |
| RC-06-06 | Recursos injetados | composição pública | NOT_RUN | — |
| RC-06-07 | Erro em construção/start | composição pública | NOT_RUN | — |
| RC-06-08 | Bundle público e offline | composição pública | NOT_RUN | — |
| RC-06-09 | Sem side effect de builder | composição pública | NOT_RUN | — |
| RC-07-01 | Doze ciclos da auditoria | liberação de objetos | NOT_RUN | — |
| RC-07-02 | Mil ciclos em lotes | liberação de objetos | NOT_RUN | — |
| RC-07-03 | Reconciliação depois de evict | liberação de objetos | NOT_RUN | — |
| RC-07-04 | Sink permanentemente lento | liberação de objetos | NOT_RUN | — |
| RC-07-05 | Resultado unknown | liberação de objetos | NOT_RUN | — |
| RC-07-06 | Callback tardio | liberação de objetos | NOT_RUN | — |
| RC-07-07 | Query após restart | liberação de objetos | NOT_RUN | — |
| RC-08-01 | Modelo explícito Codex | modelo efetivo | NOT_RUN | — |
| RC-08-02 | Modelo explícito Claude | modelo efetivo | NOT_RUN | — |
| RC-08-03 | Pi preservado | modelo efetivo | NOT_RUN | — |
| RC-08-04 | Default ausente | modelo efetivo | NOT_RUN | — |
| RC-08-05 | Modelo não suportado | modelo efetivo | NOT_RUN | — |
| RC-08-06 | Resume conflitante | modelo efetivo | NOT_RUN | — |
| RC-08-07 | Observado versus solicitado | modelo efetivo | NOT_RUN | — |
| RC-08-08 | Entrada especial e redaction | modelo efetivo | NOT_RUN | — |
| RC-09-01 | Build igual em paths diferentes | build/binding | NOT_RUN | — |
| RC-09-02 | Pi dependência alterada | build/binding | NOT_RUN | — |
| RC-09-03 | Version string falsificada | build/binding | NOT_RUN | — |
| RC-09-04 | Drift após prepare | build/binding | NOT_RUN | — |
| RC-09-05 | Três estados separados | build/binding | NOT_RUN | — |
| RC-09-06 | Capacidade por interseção | build/binding | NOT_RUN | — |
| RC-09-07 | Qualificação antiga | build/binding | NOT_RUN | — |
| RC-09-08 | Cache stale e plugins | build/binding | NOT_RUN | — |
| RC-10-01 | Pi layout usual | discovery | NOT_RUN | — |
| RC-10-02 | Windows path com espaços/Unicode | discovery | NOT_RUN | — |
| RC-10-03 | Wrapper hostil | discovery | NOT_RUN | — |
| RC-10-04 | PATH/cwd malicioso | discovery | NOT_RUN | — |
| RC-10-05 | Múltiplas instalações | discovery | NOT_RUN | — |
| RC-10-06 | Probe travado/flood | discovery | NOT_RUN | — |
| RC-10-07 | Symlink trocado | discovery | NOT_RUN | — |
| RC-10-08 | Sem autenticação de agente por discovery | discovery | NOT_RUN | — |
| RC-11-01 | Proc children indisponível | preflight/containment | NOT_RUN | — |
| RC-11-02 | Permissão de backend negada | preflight/containment | NOT_RUN | — |
| RC-11-03 | Árvore filho/neto | preflight/containment | NOT_RUN | — |
| RC-11-04 | Owner morre | preflight/containment | NOT_RUN | — |
| RC-11-05 | PID reutilizado | preflight/containment | NOT_RUN | — |
| RC-11-06 | Slot reservado sem prova | preflight/containment | NOT_RUN | — |
| RC-11-07 | Probe com backend indisponível | preflight/containment | NOT_RUN | — |
| RC-11-08 | Preflight sem segredos | preflight/containment | NOT_RUN | — |
| RC-11-09 | Shutdown e logout suportados | preflight/containment | NOT_RUN | — |
| RC-12-01 | Múltiplos alvos | attach | NOT_RUN | — |
| RC-12-02 | Troca de alvo | attach | NOT_RUN | — |
| RC-12-03 | Detach não mata | attach | NOT_RUN | — |
| RC-12-04 | Lease/revoke/shutdown externos | attach | NOT_RUN | — |
| RC-12-05 | Substrato incompatível | attach | NOT_RUN | — |
| RC-12-06 | Eventos e correlação reais | attach | NOT_RUN | — |
| RC-12-07 | Restart não reassume alvo | attach | NOT_RUN | — |
| RC-13-01 | Core+Server local | integração/providers | NOT_RUN | — |
| RC-13-02 | Core+Connector remoto | integração/providers | NOT_RUN | — |
| RC-13-03 | Mesmo wheel nas duas formas | integração/providers | NOT_RUN | — |
| RC-13-04 | MCP direto real | integração/providers | NOT_RUN | — |
| RC-13-05 | Tools-only sem Connector | integração/providers | NOT_RUN | — |
| RC-13-06 | Cliente somente stdio | integração/providers | NOT_RUN | — |
| RC-13-07 | Pi extensão autorizada | integração/providers | NOT_RUN | — |
| RC-13-08 | Multi-turn e HITL | integração/providers | NOT_RUN | — |
| RC-13-09 | Desconexão e reconexão | integração/providers | NOT_RUN | — |
| RC-13-10 | Restart dos hosts | integração/providers | NOT_RUN | — |
| RC-13-11 | Pressão e fairness | integração/providers | NOT_RUN | — |
| RC-13-12 | Consumo exclusivo/handoff | integração/providers | NOT_RUN | — |
| RC-14-01 | Migração dev0 completa | artefatos/migração | NOT_RUN | — |
| RC-14-02 | Falha no meio da migração | artefatos/migração | NOT_RUN | — |
| RC-14-03 | Wheel fora da árvore | artefatos/migração | NOT_RUN | — |
| RC-14-04 | Builds limpos comparados | artefatos/migração | NOT_RUN | — |
| RC-14-05 | Sem MCP/daemon no Core | artefatos/migração | NOT_RUN | — |
| RC-14-06 | Release parcial honesto | artefatos/migração | NOT_RUN | — |
| RC-14-07 | Pin e integridade dos consumidores | artefatos/migração | NOT_RUN | — |
| RC-14-08 | Não publicação implícita | artefatos/migração | NOT_RUN | — |
