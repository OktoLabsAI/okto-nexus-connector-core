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
| RC-02-01 | Lease com send travado | contenção/leases | PASS | seed test_f01: send blocked on normal_lock; lease expiry contains within budget; new submit refused (regression suite) |
| RC-02-02 | Força real não herda lock | contenção/leases | PASS | test_pc02_containment RC-02-02: real child peer ignoring graceful close is force-killed by the independent path (win32; linux via suite run) |
| RC-02-03 | Storage travado na expiração | contenção/leases | PASS | test_pc02_containment RC-02-03: journal worker blocked during expiry; force fires without waiting; no durable ACK invented |
| RC-02-04 | Renovação antes de fechar | contenção/leases | PASS | existing renewal-CAS tests (test_runtime) - watcher revalidates deadline under lock before containing |
| RC-02-05 | Renovação tardia | contenção/leases | PASS | fence rejects renewal/submits of closing/revoked sessions; existing revoke tests + new pre-fence |
| RC-02-06 | Revoke versus envio | contenção/leases | PASS | RC-02-07/08 tests: concurrent closers share one transition; unknown retains slot; no double release |
| RC-02-07 | Stop concorrente | contenção/leases | PASS | test_pc02_containment RC-02-07: lease+stop+shutdown concurrently; single coordination; watcher never spins on closing |
| RC-02-08 | Backend não comprova morte | contenção/leases | PASS | test_pc02_containment RC-02-08: force returned, observe NEVER_STOPPED -> outcome unknown, slot owned |
| RC-02-09 | Thread nativa retorna tarde | contenção/leases | PASS | existing late-thread tests preserved (test_runtime shutdown suite); force receipt shielded against cancellation |
| RC-02-10 | Attach sob expiração | contenção/leases | PASS | test_pc02_containment RC-02-10: attach-shaped native (no force_stop) receives close only, never signalled |
| RC-02-11 | Relógio e budgets | contenção/leases | PASS | existing clock-rollback/grace arithmetic tests; budget not restarted per retry (watcher rechecks absolute deadline) |
| RC-03-01 | Expiração durante admit | guarda pré-efeito | PASS | test_pc03_effect_guard rc-03-01: clock advanced inside admit; typed refusal, zero writes, no invented stage |
| RC-03-02 | Expiração durante marker | guarda pré-efeito | PASS | seed test_f02 (regression suite): marker-window expiry -> proven not-sent, zero effect |
| RC-03-03 | Thread inicia tarde | guarda pré-efeito | PASS | test_pc03_effect_guard rc-03-03: executor thread held; fence checked inside the thread at the write frontier; no write under stale lease |
| RC-03-04 | Revoke entre marker e write | guarda pré-efeito | PASS | test_pc03_effect_guard rc-03-04: revoke then submit -> AGENT_REVOKED before any native write |
| RC-03-05 | Revogação após início de efeito | guarda pré-efeito | PASS | existing unknown-preservation tests (rejected prompt/abort, prewrite suite) + PC02 containment of in-flight |
| RC-03-06 | Controle seguro com lease expirada | guarda pré-efeito | PASS | kernel containment exemption (interrupt/close) + existing scope tests; approval/submit blocked post-expiry |
| RC-03-07 | Controle fora do escopo | guarda pré-efeito | PASS | identity/ownership mismatch raises before effect (existing BINDING_NOT_AUTHORIZED suite) |
| RC-03-08 | Recusa com disco cheio | guarda pré-efeito | PASS | record_not_sent failure leaves conservative state (journal crash-cut suite on worker) |
| RC-03-09 | Crash após efeito | guarda pré-efeito | PASS | existing crash-after-effect cuts: possible-effect receipt blocks replay; retry same ID does not re-execute |
| RC-03-10 | Geração e clocks alterados | guarda pré-efeito | PASS | existing generation/rollback fence tests + kernel rechecks use the live clock |
| RC-04-01 | EOF com processo vivo | EOF/observação | PASS | seed test_f03: iterator EOF with live process -> EVENT_STREAM_UNAVAILABLE before write |
| RC-04-02 | EOF com journal travado | EOF/observação | PASS | memory fence before durable I/O; incident write bounded (5s) best-effort; submit refused while journal stuck (PC02 fence composition) |
| RC-04-03 | Fechamento esperado | EOF/observação | PASS | test_pc04_stream_loss rc-04-03: close-then-drain emits no stream-loss incident |
| RC-04-04 | Cancelamento inesperado | EOF/observação | PASS | CancelledError outside close fences + records once (seed waiter uses turn UNKNOWN + process RUNNING) |
| RC-04-05 | Terminal de turno sem EOF | EOF/observação | PASS | multi-turn peers keep sessions alive after terminals (existing adapter suites); EOF never conflated with idle |
| RC-04-06 | Evento terminal seguido de EOF | EOF/observação | PASS | durable terminals recorded before EOF remain replayable (journal events); session degrades separately |
| RC-04-07 | Approval pendente no EOF | EOF/observação | PASS | faulted fence blocks decide_native_approval submissions (EVENT_STREAM_UNAVAILABLE) before any new effect |
| RC-04-08 | Incidente único | EOF/observação | PASS | test_pc04_stream_loss rc-04-08: exactly one core.event_pump_failed incident per epoch |
| RC-05-01 | Fronteiras de comprimento | IDs/legado | PASS | test_pc05_identifiers rc-05-01 boundaries 0/1/159/160/161/256/257 parametrized |
| RC-05-02 | Tipos não textuais | IDs/legado | PASS | rc-05-02 parametrized non-string types: typed CoreError, no cast, no journal mutation |
| RC-05-03 | Unicode e limite de bytes | IDs/legado | PASS | bundle ID schema (maxLength 160) == Python validator; byte/Unicode ceilings separate (existing frame-codec tests) |
| RC-05-04 | Todo admitido reconcilia | IDs/legado | PASS | every admitted ID (<=160) reconciles; long IDs never admitted (rc-05-01 + existing reconcile suite) |
| RC-05-05 | Batch inválido no fim | IDs/legado | PASS | existing reconcile validation suite (converted to CoreError) + uniqueness/cardinality |
| RC-05-06 | Legado longo | IDs/legado | PASS | rc-05-06: 207-char dev0 ID readable via legacy_operation_receipt; new admission refused; read is idempotent |
| RC-05-07 | Legado não reexecuta | IDs/legado | PASS | rc-05-07: legacy read validates shape/scope; absent keys None; no cross-server leakage |
| RC-05-08 | Namespaces e prefixos | IDs/legado | PASS | internal core.internal. prefix refused externally (existing + validator); namespaces isolate (existing claim tests) |
| RC-05-09 | Hash e rekey | IDs/legado | PASS | no rekey/truncation anywhere; hashes unchanged; legacy rows read verbatim (rc-05-06) |
| RC-06-01 | EmbeddedHost público | composição pública | PASS | examples/embedded_consumer.py: open/submit/terminal/close/shutdown via create_runtime, public imports only (test executes it) |
| RC-06-02 | RemoteHost público | composição pública | PASS | examples/remote_consumer.py: same factory/artifact, executor-scoped context, persisted_lease read; no transport in Core |
| RC-06-03 | Imports privados barrados | composição pública | PASS | AST test bans native.*/offloop imports in examples+consumer_smoke; smoke migrated to create_runtime |
| RC-06-04 | Protocol completo | composição pública | PASS | protocol-completeness test: every RuntimeCore attr exists on LocalRuntimeCore (incl. persisted_lease, legacy_operation_receipt) |
| RC-06-05 | Journal alternativo | composição pública | PASS | journal Protocol decoupling + existing conformance kits (host adapter without subclassing already covered by kits) |
| RC-06-06 | Recursos injetados | composição pública | PASS | test_rc_06_06: two runtimes, isolated journals/workers; closing one leaves the other intact |
| RC-06-07 | Erro em construção/start | composição pública | PASS | create_runtime validates all inputs (TypeError) before resolving secrets/spawn; construction opens nothing |
| RC-06-08 | Bundle público e offline | composição pública | PASS | existing offline wheel consumer verification (bundle/manifest offline) re-run at PC14 with the new smoke |
| RC-06-09 | Sem side effect de builder | composição pública | PASS | create_runtime builds without spawn/network/loop (pure construction); examples prove no side effects pre-open |
| RC-07-01 | Doze ciclos da auditoria | liberação de objetos | PASS | seed test_f06: twelve open/close cycles; weakrefs collected after eviction |
| RC-07-02 | Mil ciclos em lotes | liberação de objetos | PASS | test_pc07_release rc-07-02: 1000 cycles in batches; <=16 retained adapters after gc |
| RC-07-03 | Reconciliação depois de evict | liberação de objetos | PASS | rc-07-03: receipts/snapshots after eviction (tombstone: released/CLOSED, process UNKNOWN); duplicate submit returns known receipt |
| RC-07-04 | Sink permanentemente lento | liberação de objetos | PASS | sink task awaited bounded during eviction; durable cursor design unchanged; existing slow-sink tests pass |
| RC-07-05 | Resultado unknown | liberação de objetos | PASS | unknown sessions keep slots (PC02 tests); tombstone only written for closed bindings |
| RC-07-06 | Callback tardio | liberação de objetos | PASS | rc-07-06: session absent from live registry after eviction; tombstone immutable; late completions cannot reinstall |
| RC-07-07 | Query após restart | liberação de objetos | PASS | restart queries use journal/tombstones; historical ownership never claims liveness (existing restart suites + tombstone inspect) |
| RC-08-01 | Modelo explícito Codex | modelo efetivo | PASS | seed test_f07-codex + rc-08-01: thread_start_overrides carry the explicit model to the verified native mechanism |
| RC-08-02 | Modelo explícito Claude | modelo efetivo | PASS | seed test_f07-claude + rc-08-08: ('--model', value) structured tokens in argv |
| RC-08-03 | Pi preservado | modelo efetivo | PASS | existing profiles test: pi argv keeps --model and mandatory tokens |
| RC-08-04 | Default ausente | modelo efetivo | PASS | rc-08-04: absent model -> no flag/override, defaults documented |
| RC-08-05 | Modelo não suportado | modelo efetivo | PASS | typed VALIDATION_ERROR before preparation; no silent fallback to default |
| RC-08-06 | Resume conflitante | modelo efetivo | PASS | resume params share overrides; conflicting model governed by profile fingerprint/resume grant (existing seam tests) |
| RC-08-07 | Observado versus solicitado | modelo efetivo | PASS | no fabricated effective_model anywhere; observed-model remains provider-event evidence only (earlier authorized campaigns) |
| RC-08-08 | Entrada especial e redaction | modelo efetivo | PASS | rc-08-08: Unicode/spaces/metachars travel as one structured token; invalid types/lengths refused |
| RC-09-01 | Build igual em paths diferentes | build/binding | PASS | test_pc09 rc-09-01: identical trees in two roots -> equal build_identity, unequal binding fingerprints |
| RC-09-02 | Pi dependência alterada | build/binding | PASS | rc-09-02: dependency/cli change alters the portable digest |
| RC-09-03 | Version string falsificada | build/binding | PASS | rc-09-03: same version string, different bytes -> different identities; qualification never merges them |
| RC-09-04 | Drift após prepare | build/binding | PASS | rc-09-04: content tamper between selection and prepare -> PROFILE_DRIFT before spawn (identity revalidation) |
| RC-09-05 | Três estados separados | build/binding | PASS | discovery/selection/approval/qualification remain separate states (existing suites + identity fallback never approves paths) |
| RC-09-06 | Capacidade por interseção | build/binding | PASS | capability intersection tests (allowlist) + identity fallback bounded to build content |
| RC-09-07 | Qualificação antiga | build/binding | PASS | existing fingerprint-keyed entries preserved verbatim; identity set is additive - no historical grant reinterpreted |
| RC-09-08 | Cache stale e plugins | build/binding | PASS | identity recomputed on every prepare (no stale cache); plugin/dependency changes alter the manifest digest |
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
