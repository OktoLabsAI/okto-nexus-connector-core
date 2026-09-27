# Plano C4 — correção explícita do nexus-connector-core

**Entrada auditada:** `8677145c3050b9ba270bc24ae6343d6cb391a168` · `0.2.2.dev0` · ZIP `a05e9059745d8aa7b14fc16413de3341ea022da527487ee6a38d147061d18859`.

**Natureza:** instruções para implementação sobre o HEAD atual; nenhuma correção de produto foi aplicada por esta auditoria. As tarefas começam `PENDING`. Este plano complementa C1/R3 e os achados C2/C3; não apaga histórico nem redesenha o produto.

## 1. Decisão e escopo

A rodada confirmou sete grupos de problemas por dez testes independentes. C2+C3: 28 passaram e 1 foi ignorado no conjunto completo desses dois arquivos. A correção não deve desfazer os defaults seguros, pool dedicado de força, erros estáveis, discovery/API pública, hashes mais completos e idempotência já presentes.

Prioridade P1 aqui significa risco direto de novo efeito depois da autorização/draining ou perda da rota de contenção. P2 significa defeito de recuperação, conformidade do build ou limites que também deve ser fechado antes de ratificar o escopo E1 correspondente. Não é autorização para deixar P2 indefinidamente aberto.

| Achado | Prioridade | Problema | Fase principal |
|---|---|---|---|
| T01 | P1 | Força de emergência aguarda o próprio journal | C4-01 |
| T02 | P2 | Erro normal no CAS envenena renovação/revogação | C4-04 |
| T03 | P1 | Guarda não alcança write após lock nativo | C4-02 |
| T04 | P1 | Shutdown descarta pools com open pendente e permite início tardio | C4-03 |
| T05 | P2 | Drift de executável após callback chega ao start | C4-03 |
| T06 | P2 | Conteúdo optional/peer instalado não entra no build Pi | C4-05 |
| T07 | P2 | Último arquivo ultrapassa orçamento de bytes | C4-06 |

## 2. Invariantes não negociáveis

1. MCP permanece HTTP direto do harness para Nexus Server. Core/Connector não hospedam ou fazem proxy de MCP; stdio nativo dos runtimes continua permitido.
2. Agent/autorizações/inbox/handoff continuam no Server. Core não inventa login de usuário, permissões ou controle canônico de tarefas.
3. Server local e Connector remoto consomem a mesma biblioteca e os mesmos adapters. Não corrigir nos hosts o que pertence ao Core.
4. Nunca converter timeout/cancelamento em prova de que thread/processo parou. Não repetir operação de resultado desconhecido.
5. Memória/filas/threads/tarefas são limitadas. Contenção não espera storage, callbacks ou locks de dados.
6. Qualificação de conteúdo e vínculo físico permanecem separados; configuração efetiva não pode divergir silenciosamente do que foi aprovado.
7. Não matar processos de attach externo nem confiar somente em PID; geração e prova de ownership são obrigatórias.
8. Não remover, enfraquecer ou ampliar permissões/gates para reduzir falhas da suíte.

## 3. Ordem de execução

```text
C4-00 baseline
 ├── C4-01 contenção ──┐
 ├── C4-02 efeitos ────┴── C4-03 abertura/shutdown/drift ── C4-04 CAS
 └── C4-05 conteúdo Pi ── C4-06 limites
                     todos ── C4-07 evidência e integração
```

C4-01 e C4-02 podem ser preparados em paralelo, mas ambos alteram a coordenação de runtime e precisam de revisão conjunta. C4-05/06 podem avançar separadamente. C4-04 depende do modelo de recursos de C4-03 para não introduzir outra tarefa órfã no shutdown. Dentro de cada fase, siga a sequência e registre um commit pequeno por unidade coerente; não é necessário um commit artificial por linha de checklist.

Nomes de novos tipos neste plano são conceituais. Use nomes consistentes com a API real e registre eventual adaptação. Sem renomear toda a árvore ou reescrever adapters por estética.

## C4-00 — Estabelecer baseline, fronteiras e evidência

**Achados:** T01, T02, T03, T04, T05, T06, T07. **Dependências:** nenhuma.

**Âncoras atuais:** `pyproject.toml; plans/correction-c3/evidence/S01-S08.md; tests/regression; planos C1/R3 e este pacote`. Números de linha são do snapshot, não substituem busca por símbolos.

O objetivo não é reescrever o Core nem satisfazer somente dez asserções. As correções C3 válidas ficam preservadas. As falhas desta rodada são novas combinações de requisitos já existentes: espera nativa após guarda, storage na rota de força, abertura ainda sem Session, falha de CAS, drift após callbacks e fechamento do conteúdo qualificado.

Use o HEAD real. O commit auditado é referência reproduzível, não destino de reset. Caso já exista uma correção posterior, demonstre a invariante e marque o item como resolvido por aquele commit. Trabalhe em branch própria sem apagar alterações do usuário.

### C4-00.01 — Registrar base e diferenças

**Implementar:** Registre branch, HEAD, dirty state, versão, SO/arquitetura/Python, hash do ZIP/wheel de entrada. Compare o HEAD com 8677145; identifique os arquivos que já mudaram. Não copie o snapshot sobre trabalho posterior.

**Aceite/evidência:** Manifesto com comparação e decisão por achado.

### C4-00.02 — Importar regressões sem enfraquecer condições

**Implementar:** Copie regressoes/test_review4.py para tests/regression/test_c4_audit.py. Execute as dez parametrizações e as suites C2/C3 antes de editar. Há fixtures privadas intencionais para injetar falhas; podem evoluir com o código, preservando a espera causal, o momento do vencimento e a observação do efeito.

**Aceite/evidência:** Baseline com XML; em 8677145 as dez falham. Mudanças de fixture têm justificativa antes/depois; sem xfail/skip ocultando requisito.

### C4-00.03 — Inventariar efeitos e esperas

**Implementar:** Crie EFFECT_BOUNDARIES.md: operação pública → kernel → callbacks → pool → adapter → lock/IPC → write/flush/Popen/backend físico. Inclua spawn, turn/steer, approval/input, interrupt/close, força e probes. Classifique concessão de trabalho versus contenção; marque cada await/lock e guardas existentes.

**Aceite/evidência:** Todas as operações realmente expostas têm fronteira e teste correspondente; não basta grep por to_thread.

### C4-00.04 — Separar evidências por camada

**Implementar:** Classifique testes como unitário, fault injection no caminho real, backend de SO, provider real, consumidor sintético e dois hosts reais. Registre skips/bloqueios; preserve logs anteriores e os dois warnings de fixtures identificados.

**Aceite/evidência:** Matriz não transforma synthetic peer em provider qualificado nem os 123 erros de ambiente em 123 bugs de produto.

**Gate da fase:** Baseline reproduzível e matriz de fronteiras aprovada no próprio repositório; nenhuma alteração de produto necessária apenas para preparar a auditoria.

## C4-01 — Contenção física independente de persistência

**Achados:** T01. **Dependências:** C4-00.

**Âncoras atuais:** `runtime.py: _schedule_force, _force_after_deadline (≈995–1077), _contain_expired, shutdown; journal/ports; bridge de força`. Números de linha são do snapshot, não substituem busca por símbolos.

A admissão durável de trabalho novo e o encerramento de um processo já pertencente ao Core são operações diferentes. Para trabalho, continue persistindo intenção antes do efeito. Para contenção de emergência, o journal não pode ter poder de veto ou atraso ilimitado. O defeito está no await de admit antes de force_stop, não em falta de threads: aumentar o pool não resolve.

Use uma única política de solicitação de contenção por identidade de ownership, reutilizada por expiração, shutdown e escalada de close. Pode manter funções internas distintas, desde que compartilhem a mesma regra. Estado em memória fecha admissões primeiro, força é despachada sem depender de I/O, fatos duráveis são registrados conforme possível. Não diga que existe recibo persistido quando storage não confirmou.

A força não prova morte. Até observar a árvore correta parada, preserve outcome unknown, ownership e capacidade reservada. Attach externo nunca entra nessa rota.

### C4-01.01 — Separar controle e auditoria

**Implementar:** Remova o await ilimitado de journal.admit do caminho crítico anterior a force_stop. Defina a ordem: fence em memória → reserva/coalescência de tentativa de força → despacho no recurso reservado → observação → persistência dos fatos. Uma tentativa de journal pode ocorrer em paralelo, limitada e rastreada, nunca aguardada para iniciar a força.

**Aceite/evidência:** T01 passa com admit retido por toda a observação; liberação do storage não é pré-condição para o backend receber a força.

### C4-01.02 — Unificar motivo, ownership e prazo

**Implementar:** Represente a tentativa por session/epoch/owner_generation e motivo(s), instante-limite e estado. Um novo pedido mais urgente reduz o prazo de uma tentativa ainda não despachada. Não cancele uma força física já emitida para reagendar o mesmo efeito.

**Aceite/evidência:** Shutdown zero reduz prazo de força antes agendada para o futuro; força em voo não é duplicada.

### C4-01.03 — Preservar capacidade reservada

**Implementar:** Utilize o pool de força dedicado de C3. Limite fila e tentativas por sessão; observação/close não consomem seus slots. Em saturação real do próprio backend de força, mantenha diagnóstico e unknown sem threads ilimitadas.

**Aceite/evidência:** C2 R02 e C3 S05 continuam passando; força é observada no backend e não só numa flag de coroutine.

### C4-01.04 — Representar auditoria indisponível

**Implementar:** Diferencie solicitado em memória, despachado, retorno do backend, parada observada e registro durável. Storage indisponível produz diagnóstico limitado em memória/log redigido e tentativa de reconciliação, não confirmação de commit. Não bloqueie shutdown indefinidamente em retries de journal.

**Aceite/evidência:** Erro, bloqueio e recuperação do journal não criam receipt fictício; após recuperação fatos consistentes são persistidos uma vez.

### C4-01.05 — Rastrear tarefas e cancelamento

**Implementar:** Guarde referências às tarefas de persistência/força até conclusão; callbacks consultam a tentativa correta. Cancelamento do chamador não significa cancelamento do backend nem autoriza liberar slot. Fechamento do loop sem observação mantém relatório unknown.

**Aceite/evidência:** Teste cancelamento durante admit, força e record_receipt; nenhum retry automático de trabalho nem exceção não observada.

### C4-01.06 — Provar caminhos equivalentes

**Implementar:** Execute o mesmo fault point de storage em lease expiry, explicit close que precisa escalar e shutdown. Proíba kill de PID genérico sem prova de ownership; preserve proteção de árvore/geração e tratamento de attach.

**Aceite/evidência:** Teste de processo de laboratório no SO qualificado confirma entrada física e árvore própria; alvo externo permanece vivo.

**Gate da fase:** Entrada física de força comprovada enquanto storage está retido; resultado ainda pode ser unknown até observação. Não basta mover o bloqueio para outro método.

## C4-02 — Guarda na fronteira nativa, depois de todas as esperas

**Achados:** T03. **Dependências:** C4-00.

**Âncoras atuais:** `native/runtime_bridge.py: EffectFence, _guarded_dispatch, reply_native_approval, _guarded_start; native/adapter_types.py; native/adapters/codex.py:_CodexTransport._write; Pi e Claude paths de escrita/spawn`. Números de linha são do snapshot, não substituem busca por símbolos.

A correção C3 valida no início da thread. T03 mostra uma espera posterior: o lock do transporte Codex. O mesmo princípio precisa chegar à escrita concreta de cada adaptador. O teste usa o serializer e o adapter Codex reais, com stdin de laboratório; não exige um provider para revelar a lacuna.

Implemente um guard de operação propagado explicitamente (objeto/porta interna tipada), com identidade, gerações, categoria do efeito, correlação de turno/pedido e fonte temporal compartilhada. A consulta final é síncrona, pequena e sem I/O. Dados mutáveis concorrentes devem ter leitura coerente por snapshot/versionamento ou mecanismo equivalente; não confie em uma coleção de atributos lidos incidentalmente por GIL.

Não crie servidor MCP, protocolo remoto novo nem lógica de autorização canônica no Core. O guard aplica o contexto já autorizado pelo host. Não prometa atomicidade entre consulta local e aceitação de um provider externo: o ponto garantido é que nenhuma espera interna conhecida separa a última validação da tentativa de write/spawn.

### C4-02.01 — Definir contrato do guard por operação

**Implementar:** Especifique parâmetros e resultados: permit, refused-before-effect com código estável, ou efeito possível. O guard de uma operação não pode ser sobrescrito por outra requisição. O mesmo contexto acompanha callbacks/threads/native transport.

**Aceite/evidência:** Contrato cobre deadline, draining/revoke, owner/connection generation, capability e turno/pedido quando aplicável; não contém credencial global.

### C4-02.02 — Propagar até os transportes

**Implementar:** Leve o guard pelo comando tipado até o ponto que possui o stream/process handle. No Codex, valide após adquirir _write_lock e antes de stdin.write. Equivalentes Pi e Claude devem validar depois de suas próprias travas e esperas. Não use monkeypatch de adapter em produção.

**Aceite/evidência:** T03 não grava JSON-RPC em stdin quando o clock avança durante o lock; variantes Pi/Claude mapeadas com provas próprias.

### C4-02.03 — Definir semântica de aprovação e controle

**Implementar:** Respostas que autorizam execução ou fornecem input sensível usam a guarda completa. Negar/cancelar/interromper/conter permanecem possíveis quando o deadline venceu, mas ainda exigem alvo/ownership/correlação válidos. Resposta de turno antigo não aprova turno novo.

**Aceite/evidência:** Cases de accept/input expirado não escrevem; deny/interrupt válidos chegam ao alvo, sem concessão indireta de trabalho.

### C4-02.04 — Tratar write parcial e flush

**Implementar:** Faça recusa tipada antes do primeiro efeito comprovável. Depois de uma escrita iniciada/parcial, erro ou cancelamento não pode ser convertido em not_sent/retry_safe por uma checagem tardia. Propague possível efeito ao kernel e preserve recibos.

**Aceite/evidência:** Fault point em write/flush distingue zero bytes comprovado de bytes possivelmente enviados; retry idêntico não gera segunda execução.

### C4-02.05 — Cobrir spawn e controles de inicialização

**Implementar:** Use o mesmo princípio para start, handshake e ações nativas expostas. Callback ou pool não é a fronteira final se start espera antes do spawn. Altere assinaturas internas necessárias e adapte todos os adapters; inclua limites de início/ownership descritos em C4-03.

**Aceite/evidência:** Inventário não contém write/spawn produtivo sem guard por decisão explícita; nenhuma guarda depende do polling do watcher.

### C4-02.06 — Testar concorrência sem serializar tudo

**Implementar:** Use Events/barreiras com autorização inicialmente válida, bloqueio real do lock, avanço de clock/geração e liberação. Não segure lock global do runtime durante chamada nativa para aparentar atomicidade.

**Aceite/evidência:** C2/C3 continuam passando, T03 passa e controle de força continua independente da trava de escrita.

**Gate da fase:** Todas as fronteiras do inventário de efeitos estão cobertas ou explicitamente indisponíveis; T03 passa no caminho de transporte real, não somente em fake que recusa cedo.

## C4-03 — Aberturas pendentes, shutdown e drift de configuração

**Achados:** T04, T05. **Dependências:** C4-00, C4-01, C4-02.

**Âncoras atuais:** `runtime.py: open (≈310–450), _opening, _uncertain_opens, shutdown (≈870–975), _dispose_factory_if_resolved; composition.py; native/runtime_bridge.py: factory.open; profiles.py/verify_prepared`. Números de linha são do snapshot, não substituem busca por símbolos.

Uma abertura já pode ter recursos, credenciais resolvidas ou um worker enfileirado antes de existir uma Session. Tratar somente _sessions no disposal é insuficiente. C4 exige representar essa tentativa desde a reserva e permitir que shutdown feche sua guarda.

T04 demonstrou duas falhas distintas: disposal precoce e início nativo depois de shutdown. Adicionar somente `if self._opening: return` corrige a primeira, não a segunda. Cancelar somente a coroutine também não prova que uma thread perdeu a capacidade de iniciar processo.

T05 é a janela de drift: verify_prepared acontece antes do callback de ambiente; uma atualização local do binário durante o callback chega ao start. A fixture usa uma alteração controlada no callback para representar essa janela. Não é alegação de ataque remoto nem de provider explorado.

### C4-03.01 — Representar OpeningAttempt rastreável

**Implementar:** Substitua ou complemente o Event de _opening com registro tipado da tentativa: operation/session scope, geração, guard de abertura, estado do spawn, tasks/futures, slot, owner evidence e evento de conclusão. Registre antes de qualquer callback/fila com capacidade de produzir spawn.

**Aceite/evidência:** Cancelamento do cliente não elimina tentativa não resolvida; não há duas aberturas proprietárias para o mesmo scope.

### C4-03.02 — Fechar as aberturas no início do shutdown

**Implementar:** Sob seção crítica de memória, marque draining e feche os guards de todas as tentativas ainda não efetivadas. Só depois aguarde drain. A factory/adapter recebe esse guard até o spawn.

**Aceite/evidência:** T04b: callback é liberado depois de shutdown; contador de start permanece zero. Deadline longo não contorna draining.

### C4-03.03 — Preservar supervisão de efeitos já iniciados

**Implementar:** Se o spawn já pode ter ocorrido, mantenha Future/handle e contenha quando a identificação real chegar. Não desregistre tentativa, libere slot nem devolva retry_safe apenas porque o await foi cancelado. Reconcile distingue comprovadamente não iniciado de unknown.

**Aceite/evidência:** Fault points antes/depois do spawn, resposta perdida e nascimento tardio não criam processo órfão nem duplicação.

### C4-03.04 — Corrigir condição de disposal

**Implementar:** Dispor recursos internos somente sem _opening, _uncertain_opens, sessões próprias não resolvidas, native units/forças/CAS/cleanup em voo que dependam dos pools. Verifique fechamento público idempotente sem sessions e depois de recuperação. Ownership de pools injetados pelo host é explícito.

**Aceite/evidência:** T04 passa; C3 S08 continua passando; open pendente não encontra executor shutdown e resolved shutdown libera pools.

### C4-03.05 — Revalidar lançamento depois de callbacks

**Implementar:** Revalide prepared/profile/build/binding e raiz física ao fim de environment/resume/native_action e após filas relevantes, antes do spawn. Se os bytes/refs mudaram, rejeite com PROFILE_DRIFT ou código estável equivalente antes do efeito. Não requalifique silenciosamente.

**Aceite/evidência:** T05 passa; nova configuração exige prepare/approval conforme escopo. Hash no perfil corresponde ao conteúdo que será lançado.

### C4-03.06 — Evitar I/O pesado na guarda final

**Implementar:** Faça verificação de conteúdo em worker limitado e produza snapshot selado/verificável; após esperas subsequentes, valide que o snapshot ainda corresponde aos arquivos/alvo. Use handles/identidade estável ou staging imutável controlado quando apropriado ao SO. Explique janela residual se não puder fechar troca atômica do filesystem.

**Aceite/evidência:** Hash não bloqueia event loop/força. Corridas controladas de update durante callback e fila são recusadas; não prometer eliminação universal de TOCTOU.

### C4-03.07 — Publicar lifecycle e resultados de abertura

**Implementar:** Alinhe portas, exemplos e docs sobre shutdown parcial, o que o host precisa manter vivo, consulta/retry de operação, eventuais APIs additive de final disposal. Sem exigir imports privados.

**Aceite/evidência:** Consumidor externo via wheel demonstra abrir/parar/consultar unknown/dispor em duas chamadas; nenhuma reconciliação usa só PID.

**Gate da fase:** Um shutdown que começou impede novos spawns de tentativas ainda sem efeito; tentativas com efeito possível preservam owner e capacidade até resolução. Build alterado não é iniciado silenciosamente.

## C4-04 — CAS recuperável com resultado e propriedade da tentativa

**Achados:** T02. **Dependências:** C4-00, C4-03.

**Âncoras atuais:** `runtime.py: renew_lease/revoke_lease (≈1250–1450), _late_cas_applier, _apply_committed_cas; Journal port/CAS; testes de leases`. Números de linha são do snapshot, não substituem busca por símbolos.

O booleano lease_cas_pending fica true quando uma exceção normal sai do await. O teste usa JOURNAL_FULL antes de entregar qualquer trabalho ao banco: nessa condição, o próximo pedido deve conseguir progredir.

Não corrija com `finally: pending=False` indiscriminado. Se o worker aceitou o CAS e o chamador parou de esperar, limpar a reserva pode admitir concorrência enquanto a gravação antiga ainda termina. A correção deve representar tentativa, propriedade e resultado durável. Um callback tardio nunca limpa/aplica uma tentativa mais nova por engano.

### C4-04.01 — Trocar marcador ambíguo por tentativa identificada

**Implementar:** Registre token único/revisão esperada, contexto antigo/proposto, Future durável e estado. Pode manter flag derivada para compatibilidade interna, mas a propriedade pertence à tentativa.

**Aceite/evidência:** Dois renew/revoke concorrentes não compartilham marcador sem correlação; callback verifica token antes de aplicar.

### C4-04.02 — Distinguir falha segura de resultado incerto

**Implementar:** Defina no Journal port a evidência de não entrega/não commit; por exemplo erro tipado comprovadamente pré-admissão. Para erros após entrega/commit possível, mantenha estado incerto e consulte o registro durável. Não inferir ausência de commit por qualquer Exception.

**Aceite/evidência:** Teste JOURNAL_FULL pré-delivery permite retry; commit seguido de erro não volta ao contexto anterior por suposição.

### C4-04.03 — Finalizar exceções normais corretamente

**Implementar:** Capture caminhos de erro de renew e revoke e finalize somente a tentativa correspondente. Caso comprovadamente sem commit, retire reserva; caso incerto, mantenha reconciliação rastreada e diagnóstico.

**Aceite/evidência:** As duas parametrizações T02 passam com storage recuperado; não exige reiniciar daemon nem esperar lease expirar.

### C4-04.04 — Tratar cancelamento e commit tardio

**Implementar:** Preserve shield/Future quando houver unidade aceita; registre callback/tarefa forte. Aplicação tardia revalida identidade/revisões, alvo ainda existente e fences de shutdown/revoke. Expiração/fechamento nunca é desfeita por renewal antigo.

**Aceite/evidência:** Cancelamento antes/depois de enfileirar e fault point depois do commit produzem outcomes coerentes; reaplicar não amplia autorização.

### C4-04.05 — Integrar com shutdown e recuperação

**Implementar:** Inclua CAS pendente na contabilidade de lifecycle ou resolva seu port antes de disposal. Em falha de leitura durável, contenção continua possível; não hold lock de segurança para consultar storage.

**Aceite/evidência:** CAS travado não impede força C4-01; shutdown informa pendência e callbacks tardios não operam em recursos descartados.

### C4-04.06 — Estabilizar resposta ao host

**Implementar:** Documente quando BUSY significa operação em voo, quando há recusa retry_safe e quando é necessário reconcile. Preserve códigos estáveis e contexto de erro sem segredos.

**Aceite/evidência:** Cliente não precisa interpretar substring de mensagem nem resetar _Session; consulta e tentativa seguinte possuem teste externo.

**Gate da fase:** Falha comprovadamente pré-commit não deixa busy permanente; cancelamento de um CAS aceito não permite concorrência cega nem reabertura de fences.

## C4-05 — Fechamento completo e explícito do conteúdo Pi

**Achados:** T06. **Dependências:** C4-00.

**Âncoras atuais:** `build_identity.py:_declared_dependencies/_resolve_node_modules_package/pi_build_identity; discovery.py; native/adapters/compatibility.py; docs/compatibility.md`. Números de linha são do snapshot, não substituem busca por símbolos.

C3 passou a incluir a árvore de cada dependency, mas a seleção de pacotes lê só dependencies. Optional e peer presentes podem ser carregados pelo Node sem entrar no hash. As duas fixtures executam Node e observam v1→v2 com hash igual.

Escolha uma política documentada para o layout suportado: (A) representar o conjunto instalado relevante completo, incluindo relações opcionais e peer, ou (B) recusar explicitamente layouts não representáveis. Não é aceitável aceitar o mesmo hash para código efetivo diferente. Nem é aceitável somar todo node_modules global, pois isso destrói portabilidade e vincula o build a pacotes irrelevantes.

O grafo deve preservar qual versão é resolvida por qual pacote. Dois caminhos com o mesmo nome podem resolver versões distintas. Caminhos relativos normalizados fazem parte da topologia lógica; caminhos absolutos da máquina não fazem parte da identidade portátil.

### C4-05.01 — Especificar o layout e a política de resolução

**Implementar:** Documente Node/npm layout(s) realmente suportados e rejeições: dependencies, optionalDependencies presentes/ausentes, peerDependencies e peerDependenciesMeta, hoisting/nested, aliases e symlinks/links quando existirem. Políticas não implementadas retornam unsupported, nunca hash parcial.

**Aceite/evidência:** Documento permite determinar se uma instalação é coberta antes de qualificá-la; ausência opcional normal não vira erro indevido.

### C4-05.02 — Implementar fechamento do conjunto instalado

**Implementar:** Resolva relações declaradas relevantes a partir de cada pacote. Inclua conteúdo integral de pacotes alcançados e registre relação/ausência significativa. Restrinja busca a roots confiáveis e valide nomes para evitar traversal.

**Aceite/evidência:** T06 optional/peer passa por digest diferente ou recusa explícita justificada de layout; dependência não declarada irrelevante permanece fora.

### C4-05.03 — Preservar topologia e determinismo

**Implementar:** Evite colisões de entradas deps/name quando há versões duplicadas. Normalize ordem e caminhos lógicos de instalação, trate ciclos com conjunto visitado e inclua seleção efetiva de cada importador.

**Aceite/evidência:** Mesmos bytes/layout em diretórios diferentes → mesmo build; resolução a versão diferente → outro build.

### C4-05.04 — Definir tratamento de links e ambiente de resolução

**Implementar:** Rejeite links que escapam do escopo autorizado ou mapeie-os por conteúdo com regra explícita. Não use NODE_PATH/NODE_OPTIONS herdados para transformar qualificação em execução arbitrária; valide o perfil efetivo de ambiente e hooks.

**Aceite/evidência:** Layout linkado não omite código nem lê fora do escopo silenciosamente; ambientes de teste são controlados.

### C4-05.05 — Versionar e requalificar

**Implementar:** Altere a identificação do algoritmo quando a cobertura mudar e forneça vetores before/after. Não autorize fallback automático de v2 parcial. Preserve diagnósticos/candidatos antigos como histórico e faça reprepare explícito.

**Aceite/evidência:** Allowlist do Pi só é atualizada após evidência do build real; migração não apaga journal nem altera agente.

### C4-05.06 — Validar com execução controlada e provider real separado

**Implementar:** Execute fixtures Node para optional/peer, imports/exports/implícito e portabilidade. Em etapa separada, rode o Pi real qualificado com mesma versão/conteúdo em ambiente aprovado, anotando digest e capabilities.

**Aceite/evidência:** Sem Node a prova correspondente é BLOCKED; passar unitário não autoriza afirmar provider real ou todos layouts.

**Gate da fase:** Hash de build nunca ignora código carregável de um layout declarado suportado; layouts fora dessa definição falham fechados com diagnóstico útil.

## C4-06 — Limites de leitura e enumeração efetivos

**Achados:** T07. **Dependências:** C4-00, C4-05.

**Âncoras atuais:** `build_identity.py:_add_entry/_file_digest/_add_tree e travessia do fechamento; discovery/preparation workers`. Números de linha são do snapshot, não substituem busca por símbolos.

T07 reduz o orçamento para 32 bytes e apresenta um único arquivo de 64 bytes. O algoritmo aceita porque verifica total antes de somar o arquivo. O erro independe do limite padrão de 256 MiB.

Além de corrigir a soma, evite validar limites somente depois de materializar uma árvore inteira. A inspeção encontrou uso de sorted(rglob(...)); a enumeração limitada é um requisito de hardening desta fase, não outro bug que tenha sido reproduzido por consumo massivo nesta auditoria. Não faça testes destrutivos com árvores gigantes.

### C4-06.01 — Aplicar orçamento antes do conteúdo

**Implementar:** Valide total + tamanho do próximo arquivo antes de abrir/ler quando stat for confiável; tamanho exato do limite é permitido, limite+1 é recusado. Contabilize os bytes realmente lidos para detectar crescimento concorrente.

**Aceite/evidência:** T07 passa, última entrada não contorna orçamento; recusa tipada chega ao discovery/prepare.

### C4-06.02 — Limitar travessia e memória

**Implementar:** Troque coleta global ilimitada de paths por enumeração incremental limitada, com limites explícitos de entradas, diretórios visitados, profundidade e pacotes. Para digest determinista, ordene somente material limitado ou use estrutura equivalente com cap.

**Aceite/evidência:** Milhares de diretórios vazios não burlam contador de arquivos; teste pequeno com caps reduzidos interrompe cedo.

### C4-06.03 — Proteger leitura de arquivos

**Implementar:** Use arquivos regulares e cheque mudanças entre stat/leitura; rejeite FIFO/device e loops/reparse que não atendem ao layout. Limite bytes por arquivo e total, chunks e prazo/cancelamento de trabalho. Preserve erro de drift quando houver alteração real.

**Aceite/evidência:** FIFO em plataforma compatível é recusado antes de blocking read; arquivo que cresce não excede orçamento sem erro.

### C4-06.04 — Manter responsividade e recursos limitados

**Implementar:** Hash/enumeração ficam fora do event loop e fora dos recursos de força. Cancelamento do await não inicia outro scan ilimitado; unidades ainda em execução são rastreadas, limitadas e descartadas conforme resultado.

**Aceite/evidência:** Heartbeat/força progridem com scan bloqueado; repetição não cria fila ilimitada de scans.

### C4-06.05 — Medir layout real sem elevar caps arbitrariamente

**Implementar:** Registre arquivos/bytes/profundidade/pacotes da instalação real suportada; mantenha os caps documentados ou justifique qualquer ajuste com medição e risco. Testes usam limites pequenos, nunca removem gate para passar.

**Aceite/evidência:** Build real qualificado cabe no orçamento ou retorna recusa explícita; manifesto e docs refletem os mesmos limites.

**Gate da fase:** Os limites impedem leitura/enumeração excessiva, e não apenas detectam excesso depois de consumi-lo; T07 e cenários de fronteira passam.

## C4-07 — Consolidar contratos, migrar e emitir evidência de liberação

**Achados:** T01, T02, T03, T04, T05, T06, T07. **Dependências:** C4-01, C4-02, C4-03, C4-04, C4-05, C4-06.

**Âncoras atuais:** `ports.py/models.py/composition.py/docs/api.md; tests; tools/consumer_smoke.py; contracts; release_decision; handoffs Server/Connector`. Números de linha são do snapshot, não substituem busca por símbolos.

E1 não exige que attach ou os dois aplicativos já estejam concluídos. Exige que o escopo de Core declarado funcione com as garantias de segurança e recursos, e evidência de seu backend real. E2 só é demonstrado com Server local e fluxo remoto real em dois hosts. Não converta o smoke sintético de papéis embedded/remote em E2.

As correções podem exigir alterações internas e algumas APIs aditivas, mas não devem criar dependência dos aplicativos em classes privadas. Preserve dados existentes e documente a coordenação de versão. Não publique nem faça push sem autorização específica.

### C4-07.01 — Executar matriz por camadas

**Implementar:** Rode C2/C3, dez regressões C4, cenários complementares e suite completa em SO compatível. Corrija as fixtures de close async indevido sem mudar a condição causal. Não contabilize parametrizações repetidas como descobertas independentes.

**Aceite/evidência:** XMLs de todas campanhas; nenhum warning de fixture usado como sucesso silencioso e nenhuma eliminação de teste por ausência de provider.

### C4-07.02 — Testar falhas combinadas

**Implementar:** Combine journal retido + close travado + força; abertura pendente + draining + storage indisponível; CAS cancelado + commit tardio + revogação; lock nativo + geração nova. Conte efeitos antes/depois e confirme ausência de repetição.

**Aceite/evidência:** Testes por combinação passam com gates observáveis, não só timeout de conveniência ou mock da função de topo.

### C4-07.03 — Qualificar backend e providers no escopo

**Implementar:** Execute subprocessos de laboratório com árvore própria em Linux/Windows qualificados, depois providers reais declarados. Mantenha recusa fail-closed em sandbox incompatível. Registre versão/build de cada provider.

**Aceite/evidência:** Prova física não é substituída por force Event; desconhecimento extremo pode continuar unknown, mas não pode impedir despacho por storage.

### C4-07.04 — Validar artefato isolado e API pública

**Implementar:** Gere wheel/sdist em árvore limpa, fixe hashes, instale fora do repo e execute consumers com -I. Exemplos incluem default clock, resume, shutdown com open pendente e erro estável. Schema bundle passa sem anunciar capacidades não implementadas.

**Aceite/evidência:** Mesmo wheel para os dois consumidores; no private imports; build/instalação não altera fonte do usuário.

### C4-07.05 — Preservar migrações e histórico

**Implementar:** Se houver alteração persistida de estados/algoritmo, crie migração versionada com rollback de falha seguro e backup/documentação. Não renomeie IDs arbitrariamente, não remova unknown nem resete DB. Mudança de build não rotaciona credenciais.

**Aceite/evidência:** Reabrir estado v0.2.2.dev0 mantém recibos e evidências; incertezas anteriores continuam consultáveis.

### C4-07.06 — Emitir handoff coordenado

**Implementar:** Documente mudanças da porta de native factory/guard/lifecycle, códigos, versões e algoritmo de build para agentes Server/Connector. Ofereça adaptações dentro do Core; os hosts só fornecem contexto autorizado e usam API pública.

**Aceite/evidência:** Dois consumidores compilam/rodam com versão pinada; não copiam Codex/Pi/Claude nem acrescentam proxy MCP.

### C4-07.07 — Revisar status e decisão final

**Implementar:** Cada Txx aponta para task/commit/teste/evidência. Marque PASS apenas na camada demonstrada. Relatório final declara E0/E1/E2/E3 com escopo e bloqueios, incluindo hash efetivo do wheel. Entregue diff/commits e comandos, não apenas contagem de testes.

**Aceite/evidência:** E1 somente com T01–T07 resolvidos no escopo e qualificações pertinentes; sem reclassificar bloqueador em melhoria estética.

**Gate da fase:** Decisão de liberação proporcional à evidência; nenhuma conclusão operacional apenas porque as regressões da última rodada ficaram verdes.

## 4. Contratos de estado mínimos a documentar

### 4.1. Tentativa de abertura

| Estado conceitual | Efeito possível? | Ao entrar em shutdown | Pode descartar pools/slot? |
|---|---|---|---|
| RESERVED / PREPARING | Ainda não, se não houve fronteira nativa | Fechar guard, cancelar etapas cooperativas, aguardar tarefas realmente ativas | Somente depois de comprovar que não podem iniciar efeito |
| READY / QUEUED | Ainda não, mas há trabalho enfileirado | Guard fechado acompanha a unidade até a execução | Não por cancelamento do await apenas |
| SPAWN_ATTEMPTED | Sim | Rastrear handle/future e conter quando possível | Não |
| RUNNING | Sim | Protocolo de shutdown/força normal | Depois de parada observada e tarefas finais resolvidas |
| NOT_STARTED_CONFIRMED | Não | Registrar recusa/resultado seguro | Sim, respeitando tarefas restantes |
| UNKNOWN | Talvez | Manter reserva e reconciliação; não criar substituto | Não enquanto depender da capacidade de controle |
| STOPPED_OBSERVED | Existiu e foi parado | Persistir fatos e cleanup limitado | Quando nada mais depende dos recursos |

Esses nomes não impõem novas entidades canônicas no Server. São estados internos necessários para não confundir ausência de Session com ausência de efeito possível.

### 4.2. Tentativa CAS

| Situação | Tratamento |
|---|---|
| Falha comprovadamente antes da entrega/commit | Finalizar a tentativa correspondente e liberar sua reserva; retry novo permitido |
| Unidade aceita, chamador não espera mais | Manter Future/tarefa; BUSY/pending explícito; não admitir outra tentativa conflitante |
| Commit confirmado | Aplicar somente a tentativa e geração correspondentes; não reabrir draining/revoke |
| Erro sem prova do commit | Consultar estado durável/reconciliar; não supor rollback |
| Callback tardio de tentativa antiga | Não limpar reserva nem substituir contexto de tentativa nova |
| Storage continua inacessível | Resultado incerto; contenção física independente continua permitida |

### 4.3. Recusa versus efeito possível

Antes do primeiro byte/spawn comprovado, uma recusa do guard pode produzir a evidência tipada que o kernel já converte para `record_not_sent`. Depois de um write parcial, spawn tentado ou falta de observação, use resultado incerto. O journal deve preservar esses fatos; não force `retry_safe=True` apenas para simplificar a CLI.

Para contenção, a tentativa de força pode acontecer sem admissão durável quando o banco está indisponível. A observação de parada e o estado persistido são fatos distintos: o relatório não pode alegar que a evidência está no disco sem confirmação de commit.

## 5. Matriz de efeitos exigida

Preencha o inventário com os símbolos concretos encontrados no HEAD:

| Operação | Guarda de concessão? | Verificações no ponto nativo | Teste mínimo |
|---|---|---|---|
| runtime.open / spawn | Sim | deadline + opening guard + draining + profile/build/root | callback/fila/shutdown/drift antes de spawn |
| turn.submit / steer / follow-up | Sim | deadline + geração/capability + turno + lock nativo | clock/geração muda dentro do lock |
| approval accept / permissive input | Sim | pedido e turno ativos + capability + prazo + geração | resposta aguarda write, depois vence ou troca turno |
| approval deny / cancel | Não concede trabalho | alvo/ownership/pedido válidos; sem autorização de turno novo | prazo vencido não impede negar |
| turn.interrupt / runtime.close | Contenção | ownership/geração/tipo de alvo, sem bloquear por lease vencida | send/stream/journal travado |
| force | Contenção independente | identidade física própria e generation | storage e observers retidos |
| probe ativo | Execução de diagnóstico autorizada | preflight SO antes de spawn, limites e alvo selecionado | backend indisponível recusa antes do observer |

Cada adapter precisa de casos próprios; um teste Codex não prova que Pi/Claude usam a mesma fronteira.

## 6. Como reproduzir e executar a entrega

Na raiz de uma cópia de trabalho do repositório, com ambiente Python 3.11+ e dependências disponíveis:

```bash
python -m pip install -e ".[test]"
python -m pytest -q tests/regression/test_c2_regressions.py tests/regression/test_c3_regressions.py
python -m pytest -q tests/regression/test_c4_audit.py --junitxml=evidence/c4-audit.xml
python -m pytest -q tests --junitxml=evidence/full.xml
python -m build
```

Copie o arquivo de regressões para o nome indicado antes de executar e crie `evidence/`. As dependências declaradas do snapshot são `rfc8785==0.1.4`, `jsonschema==4.26.0`; mantenha o contrato do projeto e não reimplemente canonicalização para conseguir rodar offline.

No Windows, use a mesma sequência no terminal adequado. O ambiente de prova física deve satisfazer o preflight real. Quando não satisfaz, registre BLOCKED; testes sintéticos isolados ainda podem avançar, mas não concedem qualificação de SO.

As regressões novas importam fixtures do próprio repositório e módulos privados apenas para fault injection. Isso não autoriza os aplicativos consumidores a importar privados. Os testes públicos do wheel devem continuar separados.

## 7. Entrega obrigatória do agente

Entregar: relatório de nível E0/E1/E2/E3; commits/diff; tabela T01–T07; comandos e XMLs; versão e hash do mesmo wheel para ambos os consumidores; matriz de efeitos preenchida; estado de cada teste de `03_MATRIZ_ACEITE.md`; docs públicas e handoffs; limites remanescentes e responsáveis. Nada de “feito, 10 verdes” sem confirmar cenários complementares.

Este plano contém observações de hardening a verificar (travessia limitada, prazo de força mais urgente, cancelamento nativo, layout de links). Elas são critérios de validação complementares, não alegações de bugs adicionais já reproduzidos. Ao encontrar outra falha, registre novo ID, reprodução e impacto antes de ampliar escopo.

## 8. Referências

- Código auditado: repositório `OktoLabsAI/okto-nexus-connector-core`, commit `8677145c3050b9ba270bc24ae6343d6cb391a168`. Trechos numerados em `evidencias/SOURCE_EXCERPTS.md`.
- Plano anterior: C1 `04_GATES_E_EVIDENCIAS.md`, especialmente E1 e critérios de falha; ações S01–S08 em `FIX_UPDATE_PLAN/02_ACOES_PARA_O_AGENTE.md` no snapshot.
- Python: documentação oficial de asyncio task cancellation/to_thread/shield e concurrent.futures executor cancellation. Cancelar o await não estabelece parada de uma função já executando.
- npm package.json: documentação oficial de dependencies/optionalDependencies/peerDependencies; Node 22 CommonJS modules para resolução instalada. Essas fontes fundamentam a seleção de conteúdo, não substituem testes do layout suportado.

Fontes externas consultadas: https://docs.python.org/3/library/asyncio-task.html ; https://docs.python.org/3/library/concurrent.futures.html ; https://docs.npmjs.com/cli/v11/configuring-npm/package-json/ ; https://nodejs.org/docs/latest-v22.x/api/modules.html . A auditoria executou Python 3.13.5 e Node 22.16.0; não afirma ter qualificado as versões correntes das páginas.
