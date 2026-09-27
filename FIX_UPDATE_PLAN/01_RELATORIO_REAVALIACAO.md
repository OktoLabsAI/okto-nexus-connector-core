# Reavaliação do Core 8677145 — plano C4

## 1. Conclusão

**A implementação corrigiu os cenários C3 anteriores, mas ainda existem sete grupos de problemas confirmados por dez regressões independentes. Não ratifico E1 para esta versão.** Três grupos são P1: força condicionada a storage, guarda antes — e não depois — do lock nativo de escrita, e shutdown de aberturas ainda pendentes. Os quatro P2 afetam recuperação CAS, configuração efetiva, cobertura do build Pi e limites de leitura.

Não é recomendada uma reescrita. O plano C4 propõe mudanças localizadas nas abstrações compartilhadas para fechar as mesmas invariantes em todos os caminhos. As obrigações não surgiram nesta rodada: C1 e as ações S01–S08 já exigiam guarda depois de esperas, força independente de storage, descarte condicionado à resolução e cobertura/limites do conteúdo qualificado.

### Baseline

- Commit do ZIP: `8677145c3050b9ba270bc24ae6343d6cb391a168`.
- Versão: `0.2.2.dev0`.
- ZIP: `okto-nexus-connector-core-main (2)(1).zip`.
- SHA-256 do ZIP: `a05e9059745d8aa7b14fc16413de3341ea022da527487ee6a38d147061d18859`.
- Comparação: `7a7a248db695296bb92b3f681791cc6eb2dea8c7`, v0.2.1.dev0.
- 334 arquivos originais comparados por hash; todos permaneceram inalterados. Há 21 arquivos novos/alterados em relação ao snapshot anterior. Builds foram feitos numa cópia separada.
- Os trechos consultados pelo GitHub foram fixados ao mesmo commit e seus blobs correspondem aos arquivos do ZIP. O HEAD remoto não substituiu o upload.

## 2. Execuções nesta auditoria

| Campanha | Resultado | Observação |
|---|---|---|
| Arquivos de regressões C2 + C3 completos | 28 PASS, 1 SKIP, 1 warning | Inclui as sementes e casos adicionais desses arquivos; não somar à suíte completa. |
| Novas regressões C4 | 10 FAIL | Sete achados, três com parametrização/mais de uma prova. |
| Repetição das novas regressões | 10 FAIL | Mesmas falhas, sem warnings; não conta como novos casos. |
| Suíte completa após corrigir ambiente de dependência | 657 PASS, 123 FAIL, 20 SKIP, 2 warnings | Limitada pelo backend Linux deste sandbox. |
| Wheel/sdist | Build passou | Usado backend setuptools.build_meta diretamente; não foi executado `python -m build` nem twine nesta auditoria. |
| Importação instalada e bundle NXL | Passou | Bundle explicitamente development-partial. |
| Consumidores isolados embedded e remote | Passaram | `-I`, mesmo wheel, biblioteca dentro do prefixo da venv; hosts sintéticos, não duas máquinas reais. |

### Ambiente e dependências

Python 3.13.5, Linux x86-64; pytest 9.0.2; Node v22.16.0. `rfc8785==0.1.4` não estava instalado e pip não conseguiu obter rede. Usei os arquivos upstream exatos, com blobs Git verificados (`_impl.py` = `3137d3326b98938affadb1be711ee411eb2ab86e`, `__init__.py` = `5a1f9d919643fa3bcaa0999ea66d9c535568c42a`). Não foi usado substituto simplificado de canonicalização. jsonschema 4.26.0 veio do ambiente existente.

Na primeira suíte, dois testes subprocesso falharam porque sobrescreviam PYTHONPATH e não encontravam essa dependência. Depois de torná-la disponível no ambiente de teste, repeti a suite: esses dois passaram. Resultado inicial 655/125/20 está preservado somente como histórico de setup; o resultado final é 657/123/20. A venv de consumers também recebeu a dependência exata e os pacotes já instalados; não afirmo instalação inteiramente resolvida por pip offline.

### As 123 falhas da suíte completa

Agrupamento por assinatura: 86 `capacity exhausted` por árvores não resolvidas; 24 probes sem confirmação de parada; 9 recusas `proc_children`; 2 expectativas de outro erro interrompidas antes pelo preflight; 1 assertion do guardian e 1 assertion do preflight. Este Linux não disponibiliza `/proc/self/task/<pid>/children` no formato exigido pelo backend. Isso causa falhas em cascata e retenção conservadora de slots.

Esse resultado não equivale a 123 bugs independentes nem comprova regressão de plataforma. Também não permite afirmar suíte verde aqui. Uma campanha em backend Linux/Windows realmente compatível continua necessária. Não removi o gate para contornar o ambiente.

Dois warnings correspondem a closes de fixtures `_ClockLateNative` e `_SlowThreadNative` declarados assíncronos, mas usados em fronteira síncrona. São pendências da qualidade dos testes, não os bloqueadores deste relatório.

**Nenhum provider real, campanha Windows/WSL2 ou fluxo Server–Connector em dois hosts foi executado nesta auditoria.** O Node dos dois testes de conteúdo executou pacotes sintéticos locais, não o Pi real. As evidências Windows/WSL2/Pi do repositório são afirmações apresentadas pelo projeto; não foram reproduzidas aqui.

## 3. O que melhorou em C3

O default agora compartilha relógio efetivo; o spawn enfileirado revalida no começo da thread; aprovações permissivas consultam fence na bridge; CAS saiu do lock global; força usa pool separado dos observers; o conteúdo integral dos pacotes listados passou a compor a identidade; CoreError possui código estável e mensagem separada; shutdown tenta dispor a factory quando resolvido. Esses avanços são reais e seus testes anteriores passaram.

A leitura correta é **cenários anteriores resolvidos, garantia transversal ainda parcial**:

| Correção C3 | Limite remanescente |
|---|---|
| Guarda no começo da thread | T03: existe outra espera no lock de escrita do adapter. |
| CAS fora do lock global | T02: exceção ordinária deixa reserva pendente; T01: outra rota aguarda o próprio journal antes de force. |
| Pool exclusivo de força | T01: semáforo de storage ainda impede sequer despachar nesse pool. |
| Disposal em shutdown resolvido | T04: aberturas em `_opening` não entram no predicado de resolução. |
| Árvore completa por dependency | T06: seleção omite relações optional/peer presentes; T07: orçamento soma depois da validação. |
| Verificação de prepared | T05: verificação antecede o callback de ambiente, que pode atravessar uma atualização local. |

MCP HTTP direto e a separação Core/Server/Connector continuam preservados nas alterações inspecionadas. Não identifiquei novo MCP stdio/server/proxy nesta revisão. Isso não é uma prova formal de ausência em qualquer código futuro.

## 4. Achados confirmados

### T01 — P1 — A força de emergência espera a persistência

**Fonte:** `runtime.py:_force_after_deadline`, aproximadamente 1014–1077. O método aguarda `journal.admit(... critical=True, effect_imminent=True)` antes de chamar `force_stop`. A exceção é tratada, mas uma gravação retida continua segurando o fluxo.

**Reprodução:** close do peer espera Event; a admissão do comando interno de força espera outro Event. Após o orçamento de shutdown e mais 150 ms, a função física de força ainda não foi alcançada. Somente liberar storage permite avançar. O teste usa Core e journal reais com fault injection específico, sem provider.

**Impacto:** falha de armazenamento pode impedir a contenção de um runtime já pertencente ao Core. Não é falta de threads e não é resolvido pelo pool dedicado.

**Correção:** C4-01. Separar despacho de contenção e auditoria, manter estado/ownership e journal limitado em caminho não bloqueante para força. Unknown é resultado correto enquanto não observar parada; gravar antes de poder parar é a dependência indevida.

### T02 — P2 — CAS deixa busy permanente depois de erro

**Fonte:** `runtime.py:renew_lease/revoke_lease`, aproximadamente 1297–1336 e 1414–1447. `lease_cas_pending=True` é configurado antes da espera; há recuperação de CancelledError, mas erro normal pode sair sem limpar/finalizar a tentativa.

**Reprodução:** a primeira chamada CAS lança `JOURNAL_FULL` comprovadamente antes de entregar qualquer gravação. O journal normal é restaurado. Renewal válido recebe RECONNECT_BUSY; revogação válida recebe REVOKE_BUSY. As duas parametrizações falharam.

**Impacto:** armazenamento recuperado não restaura a operação daquela lease. Não execute reset da sessão como workaround.

**Correção:** C4-04. Identidade de tentativa e resultado explícito: falha segura libera reserva; unidade aceita/incerta é reconciliada. `finally: pending=False` universal seria outra falha porque permite competir com commit tardio.

### T03 — P1 — Escrita após vencimento dentro do adapter Codex

**Fonte:** `native/runtime_bridge.py:send/_guarded_dispatch` e `native/adapters/codex.py:_CodexTransport._write`, aproximadamente 332–365. A bridge consulta o guard, mas `_write` aguarda `_write_lock` e depois escreve/flush sem consultar novamente.

**Reprodução:** CodexAppServerConnector, bridge e serializer reais; stdin é StringIO de laboratório, não processo. A autorização é inicialmente válida. O lock avisa quando o comando chegou e o relógio só então passa do deadline. Ao liberar o lock, o sink recebe JSON-RPC `turn/start` expirado.

**Impacto:** a guarda ficou na entrada da unidade de thread, não no limite nativo depois de todas as esperas. O mesmo princípio precisa ser verificado em Pi/Claude e respostas de approval/input; esses outros caminhos são critérios de teste, não defeitos adicionais já demonstrados nesta rodada.

**Correção:** C4-02. Guard por operação até o writer/spawner, consulta após a trava e antes da tentativa de efeito. Depois de bytes possíveis, preserve unknown; não transforme erro de flush em not_sent.

### T04 — P1 — Shutdown descarta recursos e permite abertura tardia

**Fonte:** `runtime.py:open/shutdown/_dispose_factory_if_resolved`; `native/runtime_bridge.py:factory.open`. O predicado de disposal verifica uncertain/live/cleanup, mas não `_opening`. O guard de start verifica deadline, sem acompanhar draining de uma abertura que já passou da primeira verificação no Core.

**Reprodução A:** abertura pela composição pública aguarda environment. `shutdown(0,0)` retorna relatório com resultado incerto, `_opening` ainda existe e a factory está marcada como disposta.

**Reprodução B:** liberar o mesmo callback depois do shutdown alcança `start` do adapter de laboratório. Não foi iniciado um Codex real; foi comprovado o alcance da fronteira de start depois de draining.

**Impacto:** uma abertura pode produzir efeito sem ter recebido fence do shutdown, com recursos de controle já descartados. São duas falhas relacionadas, não somente uma checagem booleana faltante.

**Correção:** C4-03. Registro de OpeningAttempt antes de callbacks/fila, guard fechado pelo shutdown, ownership de futures/handles mesmo sem Session, disposal somente quando toda capacidade de iniciar/controlar efeito estiver resolvida.

### T05 — P2 — Atualização local do binário depois de verify não é detectada

**Fonte:** `runtime.py:341–347` valida prepared antes de entrar na factory. A factory aguarda environment/resume/action e verifica tempo, mas não repete a comprovação de conteúdo no ponto de lançamento.

**Reprodução:** environment altera o executável selecionado depois da primeira verificação e retorna normalmente. O adapter sintético alcança start com o arquivo modificado. A fixture de qualification é controlada para isolar a política de drift; não é qualificação de um provider nem alegação de ataque.

**Impacto:** uma atualização local ou alteração concorrente pode fazer a execução diferir do build/binding aprovado. Recusar drift ao iniciar é parte da promessa já documentada, não novo requisito de sandbox absoluto.

**Correção:** C4-03. Revalidar snapshot de lançamento depois de callbacks/esperas, sem hash pesado no event loop. Preservar separação entre build e binding e declarar janela residual real de filesystem, em vez de prometer atomicidade universal.

### T06 — P2 — Build Pi ignora optional/peer presentes

**Fonte:** `build_identity.py:_declared_dependencies`, aproximadamente 164–181, seleciona somente `dependencies`.

**Reprodução:** pacote Pi de laboratório declara `helper` em optionalDependencies ou peerDependencies. O helper está instalado em node_modules e é carregado pelo entrypoint. O Node real imprime v1; o arquivo muda e passa a imprimir v2. O digest fica igual nas duas modalidades.

**Impacto:** o algoritmo pode qualificar conteúdo diferente com a mesma identidade para layouts que aceita. A árvore completa de cada dependency não resolve pacotes excluídos da seleção.

**Correção:** C4-05. Cobrir relações instaladas relevantes com resolução/topologia correta ou recusar explicitamente o layout antes de qualificá-lo. Não incorporar todos pacotes irrelevantes da máquina. Versionar algoritmo e requalificar Pi real separadamente.

### T07 — P2 — Orçamento de bytes aceita o arquivo que ultrapassa o limite

**Fonte:** `build_identity.py:_add_entry`, aproximadamente 140–149. A checagem observa `total >= limite`, depois obtém tamanho, calcula digest e soma. Não verifica o total projetado para essa entrada.

**Reprodução:** limite reduzido para 32 bytes, último e único arquivo com 64 bytes. O cálculo retorna em vez de recusar. Não foi usado arquivo gigante nem provocado consumo destrutivo.

**Impacto:** o limite documentado não é efetivo na fronteira; um arquivo final pode excedê-lo. Há também enumeração eager por rglob/sort a revisar, mas este último ponto é hardening estático, não uma segunda reprodução de consumo massivo.

**Correção:** C4-06. Validar orçamento projetado antes da leitura e bytes reais durante streaming; tornar enumeração/memória/profundidade limitadas e recusar arquivos especiais/layouts não suportados.

## 5. Plano entregue

`02_PLANO_CORRECAO_C4.md`: oito fases, 47 tarefas com implementação, âncoras, dependências e aceite; estados mínimos de abertura/CAS; matriz de efeitos; comandos e gates.

`03_MATRIZ_ACEITE.md`: 53 cenários. Dez são regressões executadas e FAIL no snapshot. Os 43 complementares estão NOT_RUN nesta auditoria. Parte pode ser coberta por testes existentes: o agente deve mapear o cenário exato, não duplicar contagens.

`regressoes/test_review4.py`: sementes com expectativas corretas, sem xfail. `backlog.json` e `matrix.json` acompanham o estado inicial de execução. `00_ENTREGAR_AO_AGENTE.md` é o prompt de implementação. `04_HANDOFF_CONSUMIDORES.md` define coordenação dos outros repositórios.

A prioridade é implementar C4-01/02/03 como garantia comum. C4-04 corrige a recuperação sem reabrir os problemas de lock. C4-05/06 podem avançar em paralelo. C4-07 só encerra com evidência proporcional ao nível declarado.

## 6. Decisão E1 e limites

A decisão de não ratificar E1 decorre dos três P1 e dos gaps de recuperação/build/limites no escopo, não da ausência de attach ou dos outros repositórios. E0 para desenvolvimento experimental com versão fixada continua adequado. E2 exige fluxo real local/remoto; não foi demonstrado aqui.

Não é possível afirmar que esta revisão esgota todo possível defeito. Os testes confirmam problemas específicos e as correções precisam de regressão, fault injection e qualificação operacional. Não foi feito pentest nem prova formal de concorrência.

## 7. Fontes e evidência

Arquivos de código exatos em `evidencias/SOURCE_EXCERPTS.md`, hash de todos originais em `evidencias/metadata.json`, logs/XMLs e comandos em `evidencias/`. Fontes externas primárias de apoio: Python asyncio/concurrent.futures; npm package.json; Node CommonJS modules, listadas no plano. O conteúdo principal deste relatório é inspeção e experimentação sobre o upload do usuário.

Wheel produzido nesta auditoria: `7c1f6aa3182d53f03d15cfdb3359d660768afcaf81da0cf435e741f589f33cb1`. Ele não é o artefato normalizado citado pelo desenvolvedor; não foi testada reprodução byte a byte do processo de normalização. Manifesto NXL: `sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630`, revisão `nxl-1-agent-centric-http-only-2026-09-25-r3`, status `development-partial`.

Nenhum código original foi corrigido, nenhum commit/push/release foi realizado. O pacote é uma auditoria com plano e regressões, não uma nova versão do produto.
