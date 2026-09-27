# Ações para o agente do Core — reavaliação de C1

Base auditada: `e6b630543a6f8b2723347d2f8cf605be86b200d6`. Confronte o HEAD antes de editar; preserve mudanças posteriores e não faça reset.

O objetivo é corrigir os achados e produzir evidência, não elaborar outro plano. Não reescrever o Core, não alterar os aplicativos, não reintroduzir MCP stdio/proxy.

## R01 — P1 — Journal sob lock global ainda bloqueia contenção e fechamento do fence por EOF

C1: PC01, PC02, PC04.

Não manter o lock de estado/segurança durante await de journal, callbacks ou comandos nativos. Separar snapshot/mutação atômica de memória, I/O e reconciliação com revalidação de geração. O latch de contenção precisa poder fechar independentemente das operações duráveis. Não mover o mesmo deadlock para outro lock.

**Aceite obrigatório:** Com get_receipt, admit, record_event e release de slot retidos separadamente, o fence fecha e a contenção física é solicitada no orçamento previsto. Persistência e recibos são reconciliados depois, sem inventar parada nem liberar slot incerto.

**Testes de partida:** `test_r01_storage_read_under_global_lock_must_not_block_lease_containment`, `test_r01b_eof_fence_must_not_wait_for_journal_read_lock`.

## R02 — P1 — Força e observação usam o mesmo pool de threads dos envios e leituras normais

C1: PC02, PC11.

Separar capacidade reservada de controle/observação do pool usado por dados e streams. Dar orçamento explícito à solicitação e à observação de contenção, com recursos limitados e ownership claro. Não resolver criando threads ilimitadas nem prometendo que cancelamento de await encerra uma thread.

**Aceite obrigatório:** Saturar totalmente os executores de envio e stream; ainda assim, a chamada física de força deve ser alcançada sem liberar os workers normais. Testar também shutdown e a ausência de confirmação de parada.

**Testes de partida:** `test_r02_force_must_have_capacity_independent_of_default_thread_pool`.

## R03 — P1 — A guarda não consulta o prazo real na thread e não cobre o spawn após callbacks

C1: PC03.

Criar uma guarda tipada vinculada à operação/sessão, com relógio monotônico corrente, deadline, gerações/revisões pertinentes e latch de contenção. Consultá-la depois de callbacks/filas e na fronteira efetiva de write/spawn. Formalizar a linearização da corrida com revoke/renew; distinguir comprovadamente não enviado de efeito possível.

**Aceite obrigatório:** Cobrir vencimento durante journal, reserva de slot, ambiente, resume callback, action callback, espera de worker e imediatamente antes de write/spawn. A guarda deve começar válida e tornar-se inválida durante a execução do teste, não nascer previamente fechada.

**Testes de partida:** `test_r03_late_dispatch_checks_clock_not_only_watcher_flags`, `test_r03b_factory_must_revalidate_after_environment_resolution`.

## R04 — P2 — Fence novo esconde recibos já persistidos em repetições idempotentes

C1: PC03, PC05.

Separar leitura autorizada de recibo/deduplicação da autorização para um efeito novo, validando identidade e hash. Não reabrir a execução só para responder ao retry nem reintroduzir I/O sob o lock de contenção ao reorganizar a ordem.

**Aceite obrigatório:** Mesmos ID/hash retornam o recibo conhecido após EOF/closing/stop; hash divergente continua sendo conflito; nenhuma segunda escrita ocorre. A resposta não deve depender da evicção já ter acontecido.

**Testes de partida:** `test_r04_duplicate_known_submit_survives_stream_fault`.

## R05 — P2 — Fila de notificações do worker cresce sem limite sob carga sustentada

C1: PC01.

Usar notificação coalescida, Condition/Event ou contabilização limitada coerente com as filas, sem perder wakeups na corrida enqueue/sleep. Verificar também justiça entre filas e reservar recursos para controles; esses últimos pontos são revisão recomendada, não novos defeitos reproduzidos nesta contagem.

**Aceite obrigatório:** Ensaio sustentado sem esvaziar filas por longos intervalos mantém notificações e memória proporcionais à capacidade configurada, não ao total processado. Testar wakeup concorrente e shutdown.

**Testes de partida:** `test_r05_wake_notifications_are_bounded_under_sustained_load`.

## R06 — P2 — Identidade de build Pi usa raiz errada e omite dependências resolvíveis fora dela

C1: PC09.

Corrigir a raiz e definir o conjunto de artefatos carregáveis: entrypoint, manifesto, dependências transitivas ou bundle autocontido comprovado. Impor limites durante enumeração e leitura. Separar esse digest portátil do binding local. Rever aceitação por fingerprint legado para que ela não contorne a cobertura nova.

**Aceite obrigatório:** Mesmo conteúdo em diretório diferente preserva a identidade; pacote irrelevante não a altera; modificar dependência executável a altera; alteração depois de prepare é detectada antes do efeito; qualificação não vira autorização de versões desconhecidas.

**Testes de partida:** `test_r06_pi_build_ignores_unrelated_sibling_package`, `test_r06b_pi_build_covers_resolvable_dependencies_outside_scope`.

## R07 — P1 — Preflight Linux consulta ABI incorreta e probes ativos não passam pelo gate

C1: PC10, PC11.

Usar ABI correta, ctypes com tipos e ponteiro apropriados, validação de retorno e erros. Passar probes ativos pelo mesmo gate de contenção antes do spawn. Preservar diagnóstico estruturado/redigido. Qualificar Win32 separadamente, sem inferir validade a partir de um teste Linux.

**Aceite obrigatório:** Teste verifica número da operação e ponteiro, não apenas status textual. Negar cada requisito de backend impede qualquer observer/spawn ativo. Rodar campanha real no SO qualificado; ambiente limitado resulta em recusa antecipada e não em cascata de processos incertos.

**Testes de partida:** `test_r07_preflight_queries_actual_subreaper_abi`, `test_r07b_active_version_probe_must_refuse_before_observer_if_containment_unavailable`.

## R08 — P2 — Helpers novos de discovery não alimentam a descoberta pública do runtime

C1: PC10.

Compor os resolvedores suportados em um único serviço de discovery público, recebendo raízes/instalações aprovadas por um contrato explícito. Preservar a distinção entre encontrar, selecionar, aprovar e executar. Não executar wrappers arbitrários para ampliar cobertura.

**Aceite obrigatório:** Os layouts declarados funcionam via a mesma API pública consumida pelos hosts, inclusive múltiplos candidatos e diagnóstico prescritivo. Nenhum consumidor importa helper privado ou reimplementa parsing de instalação.

**Testes de partida:** `test_r08_discovery_public_path_reuses_pi_layout_resolution`.

## R09 — P2 — Composição pública ainda exige tipo privado para resume e tem anotação incompatível

C1: PC06.

Publicar os DTOs/callbacks necessários em módulo suportado, com exports e Protocols coerentes. Ajustar a assinatura de environment e declarar o que é estável. Não exportar indiscriminadamente toda a bridge para resolver um único tipo.

**Aceite obrigatório:** Consumidores externos, instalados pelo wheel, exercitam composição básica e resume usando apenas imports públicos; type checking confirma que a assinatura corresponde aos objetos realmente recebidos.

**Testes de partida:** `test_r09_public_resume_contract_is_constructible_without_private_import`.

## R10 — P2 — Evicção do dicionário não libera adaptador retido por sink de eventos travado

C1: PC07.

Separar entrega de notificações da propriedade dos objetos nativos; gerenciar e cancelar tarefas cooperativas de sink com orçamento e sem confirmar entrega fictícia. Preservar cursor/replay no journal. Rastrear tarefas de cleanup no shutdown e não descartar ownership incerto.

**Aceite obrigatório:** Após parada comprovada e cleanup, um callback que não retorna não retém adaptadores pesados nem gera coleção ilimitada de tarefas. Perda de notificação continua recuperável por replay durável, sem avançar cursor de evento não entregue.

**Testes de partida:** `test_r10_stopped_session_native_is_released_even_when_host_sink_stalls`.

## Entrega

Reabra a matriz nas linhas afetadas; classifique PASS apenas para a camada realmente executada. Preserve os testes entregues como sementes e acrescente fault injection nos pontos de I/O, thread, callback, preflight e retenção. Documente nova versão/hash, migrations, comandos, plataforma, saída e riscos. Não trate as 119 falhas deste sandbox como 119 bugs independentes nem remova gates de contenção para fazê-las passar.

Publique uma decisão honesta E0/E1/E2/E3 segundo C1. E1 permanece bloqueado pelos P1 confirmados; E2 exige os hosts reais. Nenhuma publicação/push ou uso de credenciais está autorizado por este documento além do fluxo normal de implementação já acordado com o usuário.
