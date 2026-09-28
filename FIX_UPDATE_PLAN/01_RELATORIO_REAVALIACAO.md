# Reavaliação de 0.2.6.dev0 — snapshot 9f0ebab

## Conclusão

Os nove testes reconstruídos C7 e as nove sementes originais C7 passaram. W01 (sessão inexistente) e W04 (negativa de aprovação após prazo) estão corrigidos nos caminhos exercitados. W02 convergiu no caso comprovadamente sem entrega; W03 passou nos casos de close lento e recuperação após observer retido.

Ainda há **três falhas confirmadas em duas áreas**, não uma necessidade de reescrever o Core: classificação de uma lease durável mais nova (X01) e finalização/coalescência dos recursos tardios (X02 e X03). Cinco casos independentes foram executados: três falhas e dois controles positivos; a campanha foi repetida com o mesmo resultado. Só essas três falhas fundamentam este plano complementar.

Não ratifico E1 para os caminhos de geração e recuperação afetados. Isso não invalida as correções que passaram nem impede os consumidores de continuar integração experimental com pin exato. E2/E3 não foram executados nesta auditoria.

## Escopo e integridade

- ZIP analisado: `okto-nexus-connector-core-main(5).zip`.
- Commit identificado no comentário do ZIP: `9f0ebabcfb314f3f2da2221467d16a85134e475e`.
- Versão de pyproject: `0.2.6.dev0`; 378 arquivos originais.
- SHA-256 do ZIP: `52c862969e81d181fa9dc39806d8e08276f945cc38f664f3019ae164b72fdad0`.
- Baseline comparado: `12dae55381a9871958c7ffb7513030eaa66886c2` / 0.2.5.dev0.
- Diff funcional principal: runtime.py e kernel.py. O inventário completo está em `evidencias/diff_inventory.json`.
- `runtime.py` do ZIP confere com o blob GitHub `99f7eeaf6cc9c40d20a2f66fa32538405717cd06` no commit auditado.
- Não houve alteração de fonte original, reset, push ou publicação. Build feito em cópia separada.

## Resultados executados

| Campanha | Resultado |
|---|---|
| C7 entregue pelo executor | 9 PASS |
| C7 original da auditoria anterior | 9 PASS, sem alteração das sementes |
| C2–C6, campanha separada completa | 61 PASS, 1 SKIP, 1 warning |
| Cinco novos casos finais | 3 FAIL, 2 PASS |
| Repetição dos cinco casos | 3 FAIL, 2 PASS |
| Suíte completa | 699 PASS, 123 FAIL, 20 SKIP, 2 warnings |
| Wheel e sdist | PASS |
| Importação instalada e bundle | PASS, aceitação explícita de development-partial |
| Consumidor embedded e remote | PASS, ambos sintéticos, mesmo wheel |

As campanhas se sobrepõem; não somar subconjuntos nem repetições ao total. Na suíte completa, C2–C7 somam 70 PASS e 1 SKIP. Os resultados finais estão em `evidencias/RESULTADOS_RESUMO.json` e nos XMLs correspondentes.

As 123 falhas da suíte completa agrupam-se em 86 ocorrências de capacidade Linux retida por árvores não resolvidas; 24 probes sem confirmação de parada; 9 recusas diretas de proc_children; 2 asserções esperando outro erro, mas recebendo recusa de preflight; 1 teste do guardian sem evidência esperada após morte do owner; 1 teste de plataforma esperando um preflight disponível. Essa classificação está nas assinaturas e módulos dos XMLs. Não são 123 bugs independentes, nem evidência de que uma suíte completa passou neste host. Nenhum gate foi removido. As três novas falhas não dependem desse mecanismo.

Não foram executados providers reais, Windows/WSL2 ou Server–Connector em dois hosts. As campanhas anexadas pelo executor permanecem evidências declaradas por ele. Não se deduz qualificação de provider de peers sintéticos ou de exemplos de consumo do wheel.

## X01 — Conflito observado com geração durável mais nova libera o contexto antigo

**P1. Âncoras:** `runtime.py:_classify_lease_row` (1802–1820), `_apply_lease_classification` (1822–1838), `renew_lease` (1488 em diante). Contrato prévio: C7-02.02, C7-02.03 e C7-02.05.

A classificação compartilhada é uma melhoria, mas seu fallback `if lease is None or producer_done: return "NOT_DELIVERED"` não compara a linha ao contexto anterior. Assim, uma linha de geração superior que não coincide com a proposta é tratada como ausência de alteração. A aplicação dessa classificação limpa `lease_hold` e deixa a autorização antiga ativa.

### Reprodução validada

1. Abrir sessão com contexto de conexão 3, autorizado e prazo ainda válido.
2. Por uma segunda conexão SQLite real ao mesmo journal, avançar a lease para geração 5, preservando o escopo e usando CAS válido.
3. Solicitar renew para geração 4 com expected=3.
4. Confirmar `STALE_GENERATION` **no estágio lease_cas**, ou seja, a execução chegou à comparação durável, não foi recusada antes por uma fixture inválida.
5. Consultar a linha real: geração 5.
6. Solicitar novo submit pelo contexto de geração 3.

**Observado:** `SUBMITTED`, uma chamada `send_turn` no peer e hold falso. **Exigido:** contexto obsoleto recusado, zero envio produtivo. O teste de controle, sem outro escritor avançando a linha, permite renew e um submit explicitamente autorizado.

Essa concorrência não foi inventada fora do contrato: `tests/test_session_lease_state.py:test_runtime_renew_loses_to_durable_fence_moved_by_peer` já testa o avanço por outro Core/writer. O teste existente encerra na recusa de renew; a regressão nova verifica o trabalho seguinte.

O teste usa duas conexões SQLite reais, kernel e runtime reais, e peer nativo controlado. Não houve outro processo de Nexus nem execução de provider real. Não exige polling permanente do banco: uma divergência **já observada** não pode ser descartada. Não instalar o contexto durável como autoridade plena: a linha não contém todas as permissões ou o prazo local; recuperação exige o host autorizado.

## X02 — Parada observada apaga a obrigação de liberar capacidade que falhou

**P2. Âncora:** `runtime.py:_contain_late_open`, 1735–1747. Contrato prévio: C7-01.05 / C6-02.06.

Quando `observe()` retorna STOPPED, o código tenta `release_owned_slot`. Se recebe CoreError, ignora o erro e remove `_uncertain_opens`, `_late_handles` e `_opening` do mesmo jeito. A tarefa de limpeza termina sem uma obrigação identificável para o próximo shutdown.

### Reprodução

Abrir com factory retida, cancelar apenas o waiter, deixar retornar um peer tardio, observar sua parada e injetar uma única recusa pré-commit em `release_owned_slot`. Restaurar o método e chamar shutdown público duas vezes. Consultar `owned_slot_page` no SQLite.

**Observado:** uma reserva ainda ativa; nenhum late record, nenhum uncertain record, relatórios de shutdown vazios e uma única tentativa de release. **Exigido:** a obrigação permaneça identificável e convirja após o storage voltar; a reserva seja liberada com confirmação. O controle com ledger disponível libera a reserva normalmente.

Não é um processo ainda vivo nem liberação insegura de quota: o bloqueio durável fica conservador, mas sem recuperação automática pelo lifecycle que deveria possuí-lo. Pode reduzir capacidade disponível até intervenção externa. O teste demonstra esquecimento da obrigação, não corrupção do SQLite.

## X03 — Segundo shutdown sobrepõe uma força física ainda em execução

**P2. Âncoras:** `_LateHandleRecord` 190–197; `_contain_late_open` 1673–1760; `_retry_late_handles` 1761–1768; espera de cleanup em shutdown 1116–1150. Contrato prévio: C7-01.03–C7-01.05.

O registro tardio guarda native e attempt, mas não a unidade física de controle. Cada chamada de retry cria uma nova coroutine que cria novas tarefas de close e force. O shutdown pode cancelar o waiter de uma força em thread, sem parar a thread. O novo retry não identifica essa unidade ainda ativa.

### Reprodução

O peer tardio implementa `force_stop` por uma função bloqueada em thread, como a bridge faz para chamadas nativas. A primeira força começa e permanece retida em Event. Um novo shutdown público esgota seu orçamento de espera e faz a recuperação. Antes de liberar o primeiro Event, medir chamadas e concorrência na função síncrona.

**Observado:** duas chamadas físicas, duas ativas simultaneamente, peak=2, gate original ainda fechado. **Exigido:** um despacho físico ativo por operação/recurso; a segunda chamada reaproveita a tentativa em voo. Nova tentativa só depois de seu término real, quando o resultado permitir retry.

Não foi provado que um provider real morreu incorretamente ou que houve OOM. A falha comprovada é ausência de coalescência na fronteira física e duplicação de controles na recuperação. Contenção em paralelo ao close continua necessária; a correção não pode voltar ao encadeamento sequencial que já falhou.

## Qualidade das provas e limites

A fixture inicial de X01 usava uma geração fixa e poderia recusar antes do journal. Isso foi corrigido; a versão entregue exige estágio lease_cas e deriva as revisões do contexto. O controle correspondente agora passa. As evidências preliminares foram separadas e não fundamentam a conclusão. O mesmo cuidado vale para invocações iniciais do bundle sem o prefixo sha256 correto: eram erros de preparação, não do produto.

A dependência rfc8785 foi obtida pelo conector GitHub porque PyPI não era acessível por DNS. Os fontes originais v0.1.4 têm blobs verificados byte a byte; não houve substituto simplificado. Ver proveniência. Wheel/sdist foram construídos pelo backend setuptools em cópia da árvore, instalados no venv e importados fora da árvore com -I. Os hashes desta campanha são próprios, sem alegação de identidade binária com o build normalizado pelo executor.

## Decisão e próxima rodada

Concluir X01 antes de ratificar o gerenciamento de gerações em E1. Corrigir X02 e X03 na mesma rodada de recursos tardios. Manter W01/W04 fechados no escopo exercitado e preservar W02/W03 nos cenários já aprovados. Não reabrir MCP, transporte remoto, identidade ou qualificação de attach para resolver esses achados.

A correção está detalhada em `02_PLANO_CORRECAO_C8.md`. Há testes executáveis, controles positivos, runner e matriz. Testes adicionais na matriz são aceites a implementar, não alegações de falhas já demonstradas. Nenhuma correção foi aplicada ao produto nesta auditoria.
