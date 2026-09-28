# Reavaliação do nexus-connector-core — 0.2.3.dev0

## Decisão

A versão corrige os dez cenários T do relatório anterior e preserva os cenários C2/C3 verificados. Há, porém, sete grupos remanescentes U01–U07, reproduzidos em dez casos independentes. Não ratifico E1 para o escopo afetado enquanto essas falhas de autorização, supervisão e contenção persistirem. E0/integração experimental com pin exato pode continuar. Isso não é uma recomendação de reescrita nem uma recusa baseada apenas na ausência dos outros dois aplicativos.

## Baseline e método

Snapshot `3d304f9ccb1982f71410acb0a0622b0b8685a06f`, pacote `0.2.3.dev0`, extraído de `okto-nexus-connector-core-main (3).zip`. SHA do ZIP: `162e71f8674793a6a81f5b9bc664ff42ae7b01920047d5ddc3a92f0749d34083`. O commit foi obtido do comentário do arquivo; o ZIP não contém histórico Git completo. Comparação com `8677145c3050b9ba270bc24ae6343d6cb391a168`, revisão C4 e gates C1/R3 fornecidos. Os 347 arquivos originais permaneceram inalterados (hashes anexos). O build foi feito em uma cópia, não na árvore auditada.

Foram lidos o código, a matriz e as evidências C4; executados testes do repo, as sementes originais da rodada anterior com adaptação compatível, novas regressões, build e consumidores instalados. As evidências Windows/WSL2 e providers existentes no repo são declarações/campanhas do executor, não execuções reproduzidas por esta auditoria. Aqui usamos Linux/Python 3.13.5. Não executamos provider real nem fluxo Server–Connector em dois hosts.

Os testes novos isolam explicitamente qualificação/build/plataforma quando precisam alcançar uma fronteira interna. Esse isolamento NÃO concede qualificação a um provider ou a um build sintético. Não foi desabilitado o gate da suíte completa.

## Resultados reproduzidos

| Execução | Passaram | Falharam | Ignorados |
|---|---:|---:|---:|
| Testes C4 entregues no repo | 16 | 0 | 0 |
| Arquivos C2/C3 | 28 | 0 | 1 |
| Dez sementes originais C4, com wiring adaptado | 10 | 0 | 0 |
| Regressões novas + controle positivo | 1 | 10 | 0 |
| Repetição das regressões novas | 1 | 10 | 0 |
| Suíte completa no ambiente validado | 673 | 123 | 20 |

Subconjuntos sobrepõem a suíte completa; não somar números como se fossem testes diferentes. As dez falhas novas são asserções do comportamento correto, não dez exceções inesperadas de setup. Distribuição: U01=2; U02=2; U03=1; U04=1; U05=2; U06=1; U07=1. O controle positivo prova que send_turn normal está corretamente guardado após o lock; o problema de U01 é outra entrada no mesmo transporte.

A suíte completa teve dois warnings de fixtures (documentados nos logs); a repetição final nova não teve warnings. As 123 falhas agrupam-se em limitações/efeitos do backend Linux deste sandbox: 11 recusas de preflight, 86 erros por slots próprios retidos, 24 observações/probes sem prova de parada e dois casos de diagnóstico/guardian relacionados. O ambiente não possui a interface `/proc/self/task/<pid>/children` esperada. Não são 123 causas independentes, e não fundamentam isoladamente a rejeição de E1. Também não afirmamos que a suíte completa passou aqui.

A primeira campanha completa tinha mais duas falhas porque subprocessos não importavam rfc8785 do ambiente de auditoria. Isso foi corrigido somente no ambiente e a suíte foi repetida; o resultado final acima não contém essas duas falhas de dependência. Testes originais C4 precisaram apenas conectar o novo DispatchGuards do adapter ao transporte manual da fixture: a mudança e os hashes estão anexos. Uma tentativa inicial do novo controle positivo omitia poll() no processo de laboratório; foi corrigida antes das execuções finais. Esses erros de fixture/setup não são achados de produto.

## O que deve ser preservado

A força já não espera journal.admit antes de despachar; os testes T01 passam. O erro CAS comprovado antes da entrega deixa de envenenar permanentemente a reserva. O envio normal Codex passa a consultar DispatchGuards depois de _write_lock. Shutdown fecha guardas de aberturas que ainda esperam callbacks; disposal considera _opening. O algoritmo de identidade Pi inclui optional/peer efetivamente instaladas e o orçamento de bytes projetado antes da leitura foi corrigido. Preservar igualmente relógio default, DTO público de resume, discovery público e MCP HTTP direto.

Essas melhorias são reais. O que falha é estender a conclusão de uma rota testada para as demais rotas ou para resultados de falha com semântica diferente.

## Achados remanescentes

### U01 — Aprovação não instala a guarda no escritor nativo

**Prioridade:** P1. **Relação com C4:** C4-02.01/02/03/06.

**Âncoras no snapshot:** `src/nexus_connector_core/native/runtime_bridge.py:269–331; native/adapters/codex.py:1127–1171,334–373`. Intervalos são auxiliares; buscar símbolos no HEAD.

**Observação executada:** Duas parametrizações atravessaram bridge, adapter e serializer Codex reais com stdin de laboratório. A guarda começou válida. Depois de o caminho esperar em _write_lock, venceu o deadline ou mudou o turno. Em ambos os casos foi escrito o JSON-RPC id=7 com decision=accept.

**Causa:** reply_native_approval verifica a autorização/correlação antes de invocar reply, mas não instala DispatchGuards para a chamada síncrona. O escritor possui a checagem pós-lock; nesta entrada ela não recebe a guarda pertinente. Uma guarda só temporal também não revalida o pedido/turno na fronteira.

**Limite da prova:** Não foi iniciada sessão de provider real. O byte stream produzido pelo transporte real é a observação, não somente uma flag de fake.

**Tratamento:** executar a fase correspondente de `02_PLANO_CORRECAO_C5.md`, não apenas alterar a semente. Os testes negativos e os controles complementares estão em `03_MATRIZ_ACEITE.md`.

### U02 — Abertura espera no adaptador depois da última verificação

**Prioridade:** P1. **Relação com C4:** C4-02.05; C4-03.02.

**Âncoras no snapshot:** `src/nexus_connector_core/native/runtime_bridge.py:664–681; native/adapters/codex.py:292–312,684–747`. Intervalos são auxiliares; buscar símbolos no HEAD.

**Observação executada:** Duas parametrizações usaram o start do adaptador Codex real, preso em _start_lock. Após deadline vencer ou shutdown público retornar, a trava foi liberada e spawn_owned_process foi alcançado.

**Causa:** A unidade de thread verifica antes de connector.start, mas start contém esperas adicionais. A guarda de abertura não é propagada até o ponto de criação do processo.

**Limite da prova:** A primitiva de spawn foi substituída por uma sentinela que registra e lança OSError antes de criar qualquer processo. Isso comprova alcance indevido da fronteira, não execução de Codex real.

**Tratamento:** executar a fase correspondente de `02_PLANO_CORRECAO_C5.md`, não apenas alterar a semente. Os testes negativos e os controles complementares estão em `03_MATRIZ_ACEITE.md`.

### U03 — Cancelamento perde o resultado nativo tardio de open

**Prioridade:** P1. **Relação com C4:** C4-03.01/03/04/07.

**Âncoras no snapshot:** `src/nexus_connector_core/runtime.py:207–215,open/finally (~490); native/runtime_bridge.py:674–681`. Intervalos são auxiliares; buscar símbolos no HEAD.

**Observação executada:** Um start de laboratório foi bloqueado dentro da thread. O chamador de open foi cancelado. close ocorreu antes do nascimento simulado, _opening ficou vazio e _uncertain_opens reteve apenas o scope. Após shutdown e liberação da thread, o adapter retornou um handle ativo que nenhum supervisor recuperou; outro shutdown não solicitou força.

**Causa:** A tentativa mantém Event/guard, mas não o Future produtor e um observador independente do chamador. O resultado de asyncio.to_thread fica perdido após cancelamento; o finally encerra o rastreamento específico e a factory só tenta close cedo.

**Limite da prova:** O teste não criou processo de SO. Ele demonstra perda de ownership do resultado pelo lifecycle real do Core. Unknown e slot retido são conservadores, mas não substituem consumir o handle que efetivamente retorna.

**Tratamento:** executar a fase correspondente de `02_PLANO_CORRECAO_C5.md`, não apenas alterar a semente. Os testes negativos e os controles complementares estão em `03_MATRIZ_ACEITE.md`.

### U04 — Urgência maior não antecipa força já agendada

**Prioridade:** P1. **Relação com C4:** C4T-13; C4-01.02/05.

**Âncoras no snapshot:** `src/nexus_connector_core/runtime.py:1062–1088`. Intervalos são auxiliares; buscar símbolos no HEAD.

**Observação executada:** Um primeiro shutdown com orçamento de 20 segundos iniciou close travado e agendou força. Um segundo shutdown público com orçamento zero retornou sem antecipar o despacho; a sentinela de força permaneceu não chamada.

**Causa:** _schedule_force retorna quando force_task existe e ainda não terminou, mesmo se apenas dorme aguardando um prazo futuro. O parâmetro immediate não muda esse estado.

**Limite da prova:** Foi usado peer sintético para observar dispatch, sem inferir morte física. O teste libera o close no teardown e não espera 20 segundos; a decisão errada é verificável antes do prazo antigo.

**Tratamento:** executar a fase correspondente de `02_PLANO_CORRECAO_C5.md`, não apenas alterar a semente. Os testes negativos e os controles complementares estão em `03_MATRIZ_ACEITE.md`.

### U05 — Verificação final do Pi ignora CLI e dependências

**Prioridade:** P2. **Relação com C4:** C4-03.05/06.

**Âncoras no snapshot:** `src/nexus_connector_core/native/runtime_bridge.py:547–572; profiles.py:verify_prepared`. Intervalos são auxiliares; buscar símbolos no HEAD.

**Observação executada:** Prepare/build verification reais produziram um Pi Node+CLI+dependência. O callback de ambiente modificou a CLI ou um index.js dependente. Node e diretório de trabalho permaneceram iguais; o start sentinela foi alcançado em ambos os casos.

**Causa:** _launch_signature só coleta size/mtime de argv[0] e cwd. Para Pi, argv[0] é Node, não a CLI nem o conjunto qualificado. Não é uma corrida same-size/same-mtime: os arquivos omitidos foram alterados normalmente.

**Limite da prova:** Qualificação e gate de SO foram isolados para testar a janela de conteúdo; nenhum Pi real foi lançado e o teste não reivindica suporte a essa fixture como build de produção.

**Tratamento:** executar a fase correspondente de `02_PLANO_CORRECAO_C5.md`, não apenas alterar a semente. Os testes negativos e os controles complementares estão em `03_MATRIZ_ACEITE.md`.

### U06 — Erro de confirmação após commit deixa revogação só no journal

**Prioridade:** P1. **Relação com C4:** C4-04.01/02/03/04/05.

**Âncoras no snapshot:** `src/nexus_connector_core/runtime.py:1418–1488,1530–1571; ports.py:Journal; journal.py:cas_session_lease`. Intervalos são auxiliares; buscar símbolos no HEAD.

**Observação executada:** Um wrapper do SQLiteJournal real executou e confirmou o CAS de revogação, depois lançou CoreError(possible_effect=True,retry_safe=False). A consulta durável provou revoked=True. Em seguida o Core aceitou submit com o contexto anterior e chamou send_turn no peer.

**Causa:** O tratamento de Exception usa cas.done() como evidência suficiente para limpar a reserva. O resultado não é reconciliado e a memória não fica cercada. Future terminado com exceção não comprova rollback; o port permite implementar a entrega do resultado separada do commit.

**Limite da prova:** É fault injection explícita de confirmação perdida no port público do Journal, não uma alegação de que sqlite3 normalmente comita quando a própria transação falha. O teste usa persistência real e erro que declara efeito possível.

**Tratamento:** executar a fase correspondente de `02_PLANO_CORRECAO_C5.md`, não apenas alterar a semente. Os testes negativos e os controles complementares estão em `03_MATRIZ_ACEITE.md`.

### U07 — Enumeração materializa nomes antes de aplicar o limite

**Prioridade:** P2. **Relação com C4:** C4-06; C4T-45.

**Âncoras no snapshot:** `src/nexus_connector_core/build_identity.py:91–145`. Intervalos são auxiliares; buscar símbolos no HEAD.

**Observação executada:** Com 1.000 arquivos reais e limite reduzido para 4 entradas, o scanner obteve 1.000 nomes por os.listdir antes de recusar a árvore. A expectativa de interrupção incremental era no máximo o quinto nome.

**Causa:** sorted(os.listdir(current)) aloca a lista completa e a ordena antes do teste de orçamento dentro do laço. Limitar a lista final de arquivos não limita essa alocação intermediária.

**Limite da prova:** Não foi simulada falta de memória nem medido um OOM. Foi contado o trabalho efetivamente realizado pelo caminho atual; o requisito de interrupção antecipada não foi atendido.

**Tratamento:** executar a fase correspondente de `02_PLANO_CORRECAO_C5.md`, não apenas alterar a semente. Os testes negativos e os controles complementares estão em `03_MATRIZ_ACEITE.md`.

## A qualidade da evidência ainda precisa ser corrigida

O arquivo `plans/correction-c4/matrix.json` marca 52 cenários PASS e um BLOCKED. A análise encontrou mapeamentos que não demonstram o cenário alegado. Isso não autoriza apagar os testes que passam; requer delimitar a conclusão.

Exemplo concreto: `test_c4t13_zero_shutdown_shortens_scheduled_force_deadline` só chama um shutdown de 0,05 + 0,05 segundo. Não cria primeiro uma força agendada para prazo distante e depois pede encurtamento. Além disso, `report_unknown()` retorna True, sem ler o resultado. O novo U04 faz as duas solicitações reais e demonstra a ausência de antecipação. O teste anterior pode continuar útil para força após prazo curto, mas precisa de nome/escopo correto.

C4T-25/26 associam cancelamento e retorno tardio a cenário que só segura callback antes do spawn e à existência de `_uncertain_opens`. U03 demonstra a diferença entre registrar incerteza e manter o Future/handle supervisionado. C4T-19 associa aprovação à guarda na bridge; U01 mostra a espera interna posterior. C4T-45 limita arquivos coletados, não a lista intermediária criada por `listdir`. C4T-32/33 tratam erros pré-commit, não entrega perdida após commit (U06).

A evidência do executor afirma que recebeu somente Markdown e reconstruiu as sementes T. Não presumimos o que foi copiado para seu ambiente. Este pacote inclui as sementes originais e a adaptação necessária, mais o novo arquivo completo, para que a próxima rodada não dependa de reconstrução por descrição.

## Empacotamento e conformance

Wheel e sdist foram gerados pela interface `setuptools.build_meta` em cópia do repo, com log e hashes. Esta auditoria não executou toda a campanha normalizada cross-platform do projeto, nem publicação ou twine. Os hashes locais não precisam coincidir com a campanha normalizada apresentada pelo executor; não tratamos essa diferença isolada como defeito.

O wheel foi instalado na venv de auditoria, fora da árvore-fonte. `tools/consumer_smoke.py` rodou via `python -I -c` em diretório vazio nos modos embedded e remote. Ambos passaram usando o mesmo artefato. O bundle instalado passou com `allow_development_partial=True`, revision/status explicitados. Esses exemplos usam peers/projeções sintéticos: NÃO são Nexus Server e Connector executando distribuídos.

Nenhuma implementação de MCP stdio, servidor/proxy MCP foi identificada nas alterações revisadas. Isso não substitui o teste end-to-end do MCP HTTP direto, pertencente à campanha E2.

## Prioridade e ordem recomendada

Primeiro, C5-01/02: guardas finais de approvals/spawn e supervisor das aberturas. Em seguida C5-03/04: urgência de força e incerteza de CAS. Completar C5-05/06: conteúdo real do Pi e limites de enumeração. C5-00 organiza evidências antes das alterações; C5-07 valida artefatos/qualificação depois de integrar.

Server e Connector podem continuar desenvolvimento paralelo em E0 com versão fixada. Não devem contornar o Core copiando adaptadores ou chamando APIs privadas. A definição C1 de E1 permite escopo delimitado; a ausência de attach/multi-host não é, sozinha, o bloqueador desta avaliação. Os P1 reproduzidos são o impedimento.

## Arquivos entregues

`00_ENTREGAR_AO_AGENTE.md` é o prompt e a ordem de execução. `02_PLANO_CORRECAO_C5.md` contém 8 fases e 48 tarefas explícitas. `03_MATRIZ_ACEITE.md` contém 56 cenários, incluindo os executados e os ainda propostos; não é uma alegação de 56 testes implementados. `regressoes/test_review5.py` é executável e suas expectativas não devem ser invertidas. Evidências incluem logs, XMLs, hashes, resultados e diffs de fixture. Código do produto não foi alterado nem corrigido nesta auditoria.
