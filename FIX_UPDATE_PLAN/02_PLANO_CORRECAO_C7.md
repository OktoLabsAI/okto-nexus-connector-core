# Plano C7 — correções confirmadas após o C6

**Repositório:** `okto-nexus-connector-core`  
**Snapshot:** `12dae55381a9871958c7ffb7513030eaa66886c2` — `0.2.5.dev0`  
**Estado inicial das tarefas:** PENDING. O plano não contém correções aplicadas.  
**Escopo:** quatro grupos reproduzidos (W01–W04). Não reabre R3/C1–C6 inteiros nem altera escolhas de transporte.

## Objetivo

Corrigir contenção/recuperação de recursos tardios, recuperação de uma falha segura de lease, classificação de respostas negativas e a regressão de sessão ausente. Preserve as correções demonstradas: hold contra revogação incerta, ownership enquanto o produtor aguarda, restauração da aprovação pré-byte no adaptador, guards no writer, build Pi, enumeração incremental e API compartilhada.

A biblioteca continua centrada no agente e hospedada tanto pelo Server local quanto pelo Connector remoto. O Server é autoridade de domínio. Harnesses capazes de MCP usam MCP HTTP direto. Não criar MCP stdio/HTTP, proxy, relay ou servidor MCP no Core/Connector. Stdio de protocolos nativos não é MCP e continua permitido.

## Prioridade e dependências

| Achado | Prioridade | Efeito demonstrado | Fase |
|---|---|---|---|
| W03 | P1 | A força tardia depende do término de cancelamento de close; recovery deixa de alcançar um handle após observer bloqueado | C7-01 |
| W02 | P2 | Storage recuperado com falha pré-entrega comprovada não resolve hold/pending | C7-02 |
| W04 | P2 | API pública recusa decline/cancel somente pela expiração da lease produtiva | C7-03 |
| W01 | P2 | Sessão inexistente em submit/steer gera AttributeError em vez de erro tipado | C7-04 |

C7-01 tem prioridade operacional. C7-02, C7-03 e C7-04 podem avançar em paralelo depois do baseline, coordenando alterações em runtime.py. Um responsável integra essas alterações para não trocar um guard ou finalizador pelo estado anterior. Não é necessária uma nova implementação nos dois consumidores.

## Regras para interpretar prova

Uma exceção do chamador não prova rollback nem parada física. Uma requisição rejeitada antes de qualquer byte não herda possible_effect da lease que está sendo reconciliada. Unknown é correto quando faltam fatos; não justifica perder o recurso já disponível nem impedir recuperação depois de obter prova suficiente. As novas reproduções são de contrato com peers controlados e SQLite real; não equivalem a providers reais.

Leia `01_RELATORIO_REAVALIACAO.md`, `03_MATRIZ_ACEITE.md` e `regressoes/test_c7_review.py`. Para W03, releia C6-02.03–06: o pedido já era registrar antes de await e usar contenção comum, não encadear wait_for(close) seguido de force.

## Modelos mínimos de estado (implementar sem inflar a arquitetura)

### Recurso retornado tardiamente

| Estado | Dono e obrigação |
|---|---|
| OPENING | Runtime possui producer, guard e reserva; request pode parar de aguardar |
| HANDLE_OWNED_NONPRODUCTIVE | Referência forte e token de ownership registrados antes de qualquer controle |
| CLOSING / FORCE_PENDING | Tasks possuídas; prazo de força independente e antecipável |
| OWNED_UNKNOWN | Mesmo handle retido; próxima consulta/controle alcançável pelo lifecycle público |
| STOP_OBSERVED | Sem afirmar sucesso do trabalho; concluir pendências de slot/journal |
| RELEASED | Pools descartáveis somente se nenhum outro recurso/tarefa depende deles |

### Tentativa de atualização da lease

| Prova | Decisão |
|---|---|
| Produtor ainda pode comitar | Preservar tentativa e hold; controles seguros independentes |
| Falha pré-entrega/rollback comprovado + linha anterior compatível | Resolver somente a tentativa atual; revalidar autorização anterior antes de permitir novo trabalho |
| Commit de revoke confirmado | Restringir; nunca reabrir por callback de renew antigo |
| Commit de renew confirmado | Aplicar somente à sessão/revisões atuais, não draining/revogada |
| Leitura indisponível ou registro incompatível | UNKNOWN; recovery coalescida e acionável, sem remover hold por tempo |

### Resposta de aprovação

Accept ou input com conteúdo = efeito produtivo. Decline/cancel = controle negativo somente se pedido, identidade, geração, capability e mapeamento nativo continuam válidos. O host precisa estar autorizado; não há exceção genérica à autenticação HTTP. O Core distingue lease produtiva expirada de ausência de autoridade para representar o agente.

## C7-00 — Baseline e provas causais

**Achados:** W01, W02, W03, W04. **Dependências:** nenhuma.

Use o snapshot apenas como referência. O executor trabalha sobre o HEAD real, sem apagar correções posteriores. A revisão confirmou quatro grupos, não uma ordem para reabrir toda a arquitetura.

### C7-00.01 — Identificar entrada e alterações posteriores

**Implementar:** Registre commit, branch, dirty state, versão Python/SO e dependências. Compare o HEAD com 12dae55 por símbolos e comportamento. Preserve alterações do usuário; marque um achado já corrigido somente com teste correspondente. Copie todo este pacote, incluindo regressoes/, para o repositório.

**Não resolver assim:** Não fazer reset --hard, não substituir árvore inteira e não presumir que arquivos Markdown contêm as reproduções executáveis.

**Aceite:** Baseline e diff registrados; nenhum arquivo existente perdido; commit do artefato usado nos testes identificado.

### C7-00.02 — Executar sementes sem suavizar invariantes

**Implementar:** Execute executar_verificacao.py. A campanha nova tem nove casos: oito falhas esperadas no baseline e um controle positivo. Use também a versão adaptada da semente C6: a barreira observa RUNNING uma vez em vez de duas, sem alterar o teste de referência forte. Preserve logs iniciais.

**Não resolver assim:** Não usar xfail/skip para esconder falha. Não declarar a incompatibilidade da antiga barreira de observação um defeito do produto. Não encurtar teste W02 removendo o esgotamento da campanha de reconciliação.

**Aceite:** Cenários vinculados aos nós de teste; setup, falha funcional e plataforma separados. Todos os releases/barreiras de teardown continuam ativos.

### C7-00.03 — Registrar matriz de efeitos e decisões de suporte

**Implementar:** Delimite os caminhos públicos: submit/steer sem sessão, renew/revoke com resultado conhecido/incerto, finalização tardia e accept/decline/cancel. Liste callbacks, locks, tasks, registradores proprietários e writers. Nenhuma destas mudanças altera o transporte entre Server e Connector.

**Não resolver assim:** Não criar orquestração, MCP stdio/proxy, usuário Nexus ou nova inbox no Core. Não habilitar providers/plataformas para satisfazer mocks.

**Aceite:** Cada requisito aponta para o caminho realmente exercitado; limites de qualificação permanecem explícitos.

## C7-01 — Contenção comum para todo handle tardio

**Achados:** W03. **Dependências:** C7-00.

Esta é a prioridade P1. As linhas runtime.py:1653–1730 ainda implementam um segundo fluxo sequencial close→force→observe. O timeout de wait_for espera que o cancelamento de close termine; uma operação cooperativa que precisa aguardar um backend pode impedir a força. Além disso, o handle só entra em _late_handles depois da observação: cancelar a tarefa nesse intervalo deixa a tentativa em _opening, mas sem uma rota ativa de recuperação.

Reaproveite o coordenador de recursos possuídos já usado pelas sessões. Não acrescente outra camada de timeout ao mesmo encadeamento. O critério é capacidade de despachar controle sobre o mesmo recurso, não a promessa de que o SO sempre o encerrará.

### C7-01.01 — Registrar propriedade antes do primeiro await

**Implementar:** Transfira o native retornado para um registro forte, único, do runtime antes de close, observe, force ou I/O de journal. Guarde attempt_id, scope, epoch, contexto necessário, owner/birth evidence, slot e tasks. O registro é não produtivo: não o publique como READY. OpeningAttempt pode transferir ownership, nunca removê-lo sem substituto.

**Não resolver assim:** Não guardar apenas em uma variável local de coroutine nem depender do Future concluído em _opening como mecanismo de recuperação. Não registrar só depois de observe retornar.

**Aceite:** W03b encontra o mesmo recurso pelo lifecycle público durante e depois de uma observação bloqueada. Callback duplicado não cria outro proprietário.

### C7-01.02 — Delegar o encerramento ao coordenador comum

**Implementar:** Componha o registro tardio com a mesma interface de close/force/observe dos recursos normais. Pode adaptar _Session ou extrair uma visão comum mínima; preserve os adaptadores. Use o prazo absoluto já vigente do shutdown/lease, não uma nova tolerância calculada da hora de chegada do handle.

**Não resolver assim:** Não manter uma implementação paralela simplificada em _contain_late_open. Não usar cleanup_budget_seconds como nova autorização para trabalhar ou como extensão do prazo de força.

**Aceite:** C6-02.04 fica atendido por mecanismo compartilhado; shutdown(0,0) mantém urgência mesmo se o handle só chega depois.

### C7-01.03 — Agendar a força independentemente de close e cancelamento

**Implementar:** Mantenha close numa task possuída; agende a força em task/capacidade separada antes de aguardar close. Um timeout do waiter apenas encerra a espera. O cancelamento de close pode ser solicitado como tentativa cooperativa, mas a sua conclusão não é pré-condição para chamar force_stop. Conserve a capacidade reservada já implementada.

**Não resolver assim:** Não usar await wait_for(close) seguido de force como rota de emergência. Não resolver aumentando timeout, liberando artificialmente a barreira do teste ou criando threads ilimitadas.

**Aceite:** W03 passa mantendo close bloqueado mesmo após ele observar CancelledError. A sentinela de força é alcançada sem liberar close. Storage e observers não ocupam o despacho reservado.

### C7-01.04 — Separar cancelamento do chamador e supervisão

**Implementar:** Shutdown pode devolver unknown quando esgota seu orçamento; o registro proprietário e suas tasks não devem desaparecer por cancelamento de gather do waiter. A espera pública pode usar asyncio.wait ou shield conforme a propriedade; observe exceções das tasks mantidas. Não deixe asyncio.wait_for(gather(...)) destruir a única rota de recovery.

**Não resolver assim:** Não engolir CancelledError como prova de parada; não capturar BaseException e limpar o registro independentemente do estado físico.

**Aceite:** W03b: primeira força falha, observe bloqueia, shutdown expira; após restaurar o backend, uma segunda chamada alcança a força no mesmo handle. Sem novo spawn.

### C7-01.05 — Coalescer recuperação e finalizar estado físico/durável separadamente

**Implementar:** Um registro possui no máximo a quantidade prevista de controle em voo. Segunda chamada reaproveita ou antecipa a tentativa pendente; falha concluída permite retry limitado sobre o mesmo owner. Após STOPPED, finalize ledger e recibos. Se release_owned_slot falhar, conserve obrigação durável explícita. Só então permita disposal dos pools dispensáveis.

**Não resolver assim:** Não chamar close/force repetidamente em paralelo a cada shutdown. Não apagar unknown no mesmo except que ignora falha no ledger. Nunca force attach/externo por PID isolado.

**Aceite:** Recuperação atinge STOPPED quando o backend volta; falha de persistência não inventa liberação. Repetição de shutdown é idempotente e recursos externos ficam intocados.

### C7-01.06 — Provar a transferência e a independência

**Implementar:** Execute W03/W03b, as sementes C6 e cenários de close cancelável, close que demora a cancelar, force que falha, observer indisponível, journal bloqueado e shutdown cancelado duas vezes. Em SO qualificado, utilize processo de laboratório controlado pelo backend real, com prova de nascimento.

**Não resolver assim:** Não tratar native fake como qualificação de Codex/Pi/Claude real. Não exigir matar processo alheio para ter teste verde.

**Aceite:** Evidência distingue despacho observado no peer, chamada real de backend, STOPPED e commit. Quando backend não está disponível, essa campanha fica BLOCKED, não PASS.

## C7-02 — Convergência da tentativa de lease após recuperar storage

**Achados:** W02. **Dependências:** C7-00.

As recusas conservadoras adicionadas pelo C6 devem ser preservadas. O defeito observado não é conceder trabalho após revogação: é nunca recuperar uma operação cujo CAS falhou comprovadamente antes da entrega, após uma falha temporária na leitura. O finalizador direto conhece producer_done; o reconciliador repete uma segunda lógica que não possui essa informação. Nos testes, ele executou as 20 tentativas, releu a linha antiga e terminou mantendo hold e pending.

Não corrija liberando toda incerteza depois de um número de tentativas. Use prova de término e resultado da tentativa correta.

### C7-02.01 — Materializar o registro da tentativa

**Implementar:** Defina LeaseUpdateAttempt tipado ou equivalente com token atribuído na reserva, contexto anterior/proposto, ação, Future produtor, desfecho conhecido, evidência de não entrega/commit, último estado durável e tarefa reconciliadora. Passe o token capturado para todos os callbacks desde sua criação.

**Não resolver assim:** Não capturar o token atual somente quando o callback começa: isso não identifica a tentativa original. Não usar um booleano isolado para representar entrega, commit, cancelamento e resolução.

**Aceite:** Finalizador antigo não altera tentativa nova. Estado do produtor continua consultável pelo reconciliador sem que o cliente precise repetir o CAS.

### C7-02.02 — Usar uma única função de transição

**Implementar:** Extraia a decisão a partir de tentativa, resultado do produtor e linha durável para uma função compartilhada por caminho direto, callback tardio e retries. Ela retorna classificação/ações; agendamento é separado. Compare scope, owner, connection generation, autorização, configuração e revoked. Não sobrescreva memória mais nova.

**Não resolver assim:** Não manter outra versão abreviada da classificação dentro do laço de retry, com comparação de apenas duas revisões. Não fazer consulta de SQLite sob o lock de contenção.

**Aceite:** As mesmas provas produzem as mesmas transições nos três caminhos; W02 renew/revoke não fica preso por cair na rotina de retry.

### C7-02.03 — Resolver a falha segura quando há prova suficiente

**Implementar:** Se o produtor terminou com recusa pré-entrega comprovada ou rollback comprovado e a linha consistente confirma o contexto anterior, finalize a tentativa e remova somente seu hold. Revalide estado atual: sessão já encerrando, revogada ou expirada não volta a conceder trabalho. Não reaplique automaticamente o pedido que falhou.

**Não resolver assim:** Não inferir rollback de Exception, Future.done, linha antiga isolada ou contador de retries. Não disparar novo CAS nem nova tarefa do agente como forma de descobrir o resultado.

**Aceite:** W02 conclui o reconciliador e permite um novo submit explicitamente solicitado com autorização ainda válida; nenhuma segunda execução do CAS ou do trabalho anterior.

### C7-02.04 — Manter unknown genuíno e tornar a retomada explícita

**Implementar:** Quando a prova não existe, preserve hold e permissões de contenção. Após esgotar o orçamento de retries, exponha estado consultável e um gatilho de retomada documentado/coalescido, ou continue recuperação limitada acionada por disponibilidade. A API não pode depender de acesso a binding.lease_hold pelo host.

**Não resolver assim:** Não limpar a barreira pelo timeout; não deixar um estado silencioso que somente reiniciar a aplicação recupera. Não criar uma task de retry por submit.

**Aceite:** Falha de ACK após commit continua bloqueando trabalho; storage que retorna converge. Consumidor conhece status e recuperação pública sem editar flags privadas.

### C7-02.05 — Preservar token e revisão nas corridas

**Implementar:** Revalide token depois dos awaits. Proteja disputas entre renew/revoke, shutdown, resultado tardio e reconciliação. Uma revogação durável restringe imediatamente; um renew tardio só aplica se a sessão ainda é a mesma, não produtivamente encerrada e com revisões compatíveis.

**Não resolver assim:** Não remover hold de outra tentativa. Não descartar tarefa produtora apenas porque o request HTTP/SSE/WSS do host terminou; o transporte continua fora do Core.

**Aceite:** Testes de callback antigo, commit tardio e linha mais nova não ressuscitam autorização nem impedem a força.

### C7-02.06 — Validar disponibilidade e segurança juntas

**Implementar:** Execute W02 deixando completar o orçamento real do reconciliador; adicione um controle de commit com ACK perdido e leitura indisponível, preservando as sementes C6. Registre cada transição sem credenciais. Inclua um Journal alternativo conforme o port e SQLite real para comprovar o registro.

**Não resolver assim:** Não obter PASS usando mock que sempre devolve revoked=True nem saltando a falha de leitura que leva ao reconciliador.

**Aceite:** Um caso comprova recuperar rollback/não entrega; outro comprova não liberar incerteza. Logs mostram produtor terminado, revisões lidas, token e decisão.

## C7-03 — Rejeição segura pela API pública de aprovações

**Achados:** W04. **Dependências:** C7-00.

O adaptador já permite decline/cancel após a lease produtiva expirar, mas a chamada pública não chega até ele: _authorize e _session exigem lease viva, e OperationKernel classifica como contenção apenas turn.interrupt/runtime.close. Corrigir só uma dessas verificações desloca a mesma falha para a próxima.

Isto NÃO é permissão para aceitar credenciais HTTP vencidas, ignorar autenticação do Server ou representar outro agente. O host continua validando o operador/agente e o escopo. A exceção é da lease produtiva local para uma resposta estritamente negativa a um pedido ainda observado e do mesmo alvo.

### C7-03.01 — Classificar decisão e efeito uma única vez

**Implementar:** Após validar NativeApprovalOperation, derive internamente a categoria do efeito. Accept e input que entregam dados continuam produtivos; decline/cancel só são contenção quando o mapeamento nativo é comprovadamente negativo. Não aceite um parâmetro de usuário skip_auth ou containment=True.

**Não resolver assim:** Não isentar a ação approval.decide inteira: ela também carrega accept. Não mapear ausência de resposta para aprovação implícita.

**Aceite:** Controle accept de W04 permanece recusado depois do prazo; decisões desconhecidas e payloads inválidos não chegam ao peer.

### C7-03.02 — Propagar a semântica pelas três fronteiras

**Implementar:** Use a mesma classificação em _authorize, _session e OperationKernel, além do writer. Preserve validação de allowed_actions, identidade, binding, geração, sessão, hash do pedido e turno. A exceção temporal só vale para a resposta negativa, não para capacidade nova.

**Não resolver assim:** Não remover as guardas produtivas nem evitar journal para decline. Não mudar hashes de operações antigas sem análise de compatibilidade.

**Aceite:** W04 decline/cancel passa pelo método público e produz exatamente uma resposta negativa; accept continua zero efeito.

### C7-03.03 — Preservar correlação e estado bifásico do pedido

**Implementar:** Mantenha a correção C6 no adaptador: reservar não é consumir. Recusa pré-byte restaura somente a reserva proprietária enquanto pedido/turno permanecerem válidos; escrita parcial mantém unknown e não permite reenviar. A mesma regra vale para o estado pending do Core.

**Não resolver assim:** Não aprovar turno novo com pedido antigo; não voltar pending=True após erro de flush que pode ter enviado dados.

**Aceite:** Sequência accept recusado antes do write → decline público no mesmo pedido funciona; terminal/turno alterado/ID divergente continuam recusados.

### C7-03.04 — Definir compatibilidade e provas por adaptador

**Implementar:** Documente a mudança temporal da API sem ampliar permissões de rede. Use testes da entrada pública, kernel e writer; cubra Codex e Claude somente nas rotas declaradas. A inexistência de mecanismo de input negativo em um adaptador deve ser capability explícita, não inventada.

**Não resolver assim:** Não validar apenas CopiedAdapterSession.reply_native_approval e dizer que a API completa passou. Não reintroduzir proxy MCP para viabilizar respostas.

**Aceite:** Recibos e serialização preservam códigos e resultado de efeito; consumidor instalado demonstra decline permitido e accept recusado no mesmo estado.

## C7-04 — Erros tipados para sessão ausente

**Achados:** W01. **Dependências:** C7-00.

Esta é uma regressão localizada, sem necessidade de novo subsistema. _send permite fence_binding=None para delegar a _session, mas antes disso o novo elif consulta fence_binding.lease_expired. O resultado é AttributeError em submit/steer de uma sessão desconhecida.

### C7-04.01 — Corrigir o fluxo nulo sem enfraquecer deduplicação

**Implementar:** Depois do lookup autorizado do recibo conhecido, resolva ausência da sessão com a validação tipada existente, ou proteja todas as leituras do binding e chegue a _session. Fixe a ordem de erros de draining/sessão ausente de forma documentada.

**Não resolver assim:** Não usar except AttributeError global. Não mover exigência de sessão viva antes do lookup de recibo: isso quebraria replay após evicção.

**Aceite:** W01 submit e steer retornam CoreError(SESSION_UNKNOWN) em sessão nunca existente; nenhuma escrita ou slot novo.

### C7-04.02 — Cobrir estados adjacentes

**Implementar:** Teste ID válido inexistente, sessão removida, sessão fechada, contexto de outro agente e shutdown em andamento. Para IDs já conhecidos, confirme recibo idêntico e conflito de hash sem necessidade de processo vivo.

**Não resolver assim:** Não criar sessão automaticamente para satisfazer submit nem converter toda recusa em SESSION_UNKNOWN ocultando autorização.

**Aceite:** Contratos de erro por estado preservados; zero AttributeError/500 acidental; seeds de deduplicação C2 permanecem verdes.

### C7-04.03 — Testar contrato fora da árvore

**Implementar:** Execute chamada pública contra wheel instalado e serialize o CoreError pelo modelo existente dos hosts. A implementação não requer mudar protocolo NXL: ajuste schema somente se houver nova informação pública realmente necessária.

**Não resolver assim:** Não corrigir nos consumidores capturando exceções privadas nem duplicar validação de runtime em Server/Connector.

**Aceite:** Mesmo resultado tipado em consumo local e sintético remoto usando um único wheel.

## C7-05 — Qualificação delimitada e entrega

**Achados:** W01, W02, W03, W04. **Dependências:** C7-01, C7-02, C7-03, C7-04.

Não há dependência de terminar o Server ou Connector para corrigir W01–W04. Os hosts reais são necessários para E2, não para reproduzir estes contratos. A correção deve ser entregue com distinção entre implementação, regressão, backend real e provider real.

### C7-05.01 — Executar a campanha sem inflar contagens

**Implementar:** Rode as nove regressões novas, C6 original adaptado, C5 original e testes históricos/entregues. Rode a suíte completa no SO-alvo qualificado. Registre falhas ambientais como falhas/bloqueios de campanha, nunca PASS; subconjuntos não são somados ao total.

**Não resolver assim:** Não remover require_containment para deixar o sandbox verde. Não usar os testes fakes como prova de término de uma árvore real.

**Aceite:** XMLs, comandos, exit codes e dependências anexados; as oito falhas atuais tornam-se PASS sem perder o controle accept.

### C7-05.02 — Verificar artefato e contratos compartilhados

**Implementar:** Gere wheel/sdist em árvore limpa e instale fora do checkout. Verifique o bundle com hash fixado e status correto, API pública e consumidores. Documente possíveis mudanças additive de recovery/lifecycle para os dois apps, sem imports privados.

**Não resolver assim:** Não anunciar development-partial como contrato normativo completo. Não publicar pacote nem fazer push/release sem autorização pertinente.

**Aceite:** Wheel identificado por hash; mesmo artefato entregue a Server e Connector; MCP HTTP continua direto e não existe servidor/proxy MCP no Core.

### C7-05.03 — Encerrar com estados e riscos verificáveis

**Implementar:** Atualize backlog e matriz por evidência, não por número de testes. Reporte o escopo elegível E1 e o que ainda depende de backend/provider real. Se W03 não estiver comprovado, não marque a contenção tardia como concluída. E2 exige fluxo real local/remoto; E3 é o escopo restante acordado.

**Não resolver assim:** Não transformar limitações já declaradas de attach/outros providers em novos bugs desta rodada. Não declarar aprovação universal por ausência de outros achados.

**Aceite:** Relatório final explicita commits, linhas alteradas, cenários PASS/FAIL/NOT_RUN/BLOCKED, migrações, riscos e owners. Não precisa produzir outro plano no lugar da implementação.

## Saída obrigatória do agente

Entregue código e testes, não outro plano no lugar da execução. Inclua commit(s), baseline/HEAD, diff, versões/hashes do wheel e bundle, comandos, XMLs, atualização da matriz, mudanças públicas e lista precisa de pendências. Não publique nada por inferência deste plano. O relatório distingue implementação pronta de qualificação não executada.

A API de erro de sessão ausente não precisa de migração de dados. Eventual novo estado transitório de tentativa também não obriga alteração de schema: só versionar persistência se uma obrigação precisa sobreviver a restart, explicando como registros antigos continuam reconciliáveis. Retenção de ownership não significa manter recursos para sempre: mantenha recursos enquanto há ownership, finalize quando houver comprovação e respeite limites de capacidade.
