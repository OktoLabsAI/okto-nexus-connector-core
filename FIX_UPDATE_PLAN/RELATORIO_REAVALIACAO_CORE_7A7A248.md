# Reavaliação do nexus-connector-core — 7a7a248 / 0.2.1.dev0

**Objeto:** ZIP enviado pelo usuário, após a rodada C2 de correções dos achados R01–R10.  
**Commit identificado no ZIP:** `7a7a248db695296bb92b3f681791cc6eb2dea8c7`.  
**Comparação:** `e6b630543a6f8b2723347d2f8cf605be86b200d6`, pacote `0.2.0.dev0`.  
**Referências de aceite:** plano C1, revisão arquitetural R3 e relatório anterior R01–R10.  
**Natureza:** inspeção estática, comparação de snapshots e testes executados nesta auditoria; não é uma versão corrigida do produto.

## 1. Parecer executivo

**As correções são reais e vários cenários anteriores deixaram de falhar. Contudo, E1 ainda não pode ser ratificado independentemente.** Os 14 testes nomeados da rodada C2 passam neste ambiente. Testes adicionais reproduzem **oito grupos de problemas, em 11 casos**, incluindo cinco grupos P1 relacionados à autorização e à independência da contenção.

Os problemas não exigem reescrever o Core nem mudar a divisão entre os três aplicativos. Exigem concluir duas garantias transversais: toda operação com efeito deve verificar a autorização na fronteira efetiva; a contenção física não pode ficar na fila de armazenamento ou de observações/encerramentos travados.

Há também pendências de identidade de build do Pi, contrato de erro e descarte do executor interno. O Core pode continuar sendo consumido como preview experimental com versão fixada. Não recomendo substituição operacional dos runtimes nos aplicativos consumidores enquanto os P1 persistirem.

A ausência de attach e de teste remoto real não é o motivo desta recusa de E1: esses itens pertencem a gates posteriores ou a escopos específicos. Os achados P1 ocorrem dentro do próprio escopo gerenciado que se pretende liberar.

## 2. Identificação, integridade e limites

| Item | Evidência |
|---|---|
| ZIP SHA-256 | `99cfc660e231ff2da71738508894c827bbdd69f1e73ccddc8a483f56a17687e4` |
| Arquivos originais | 332; comparação pós-auditoria confirmou 332 inalterados |
| Alterações relativas ao snapshot anterior | 23 modificados, 5 adicionados e 5 removidos; inventário no pacote |
| Python utilizado | 3.13.5 |
| Ambiente | Linux x86-64, kernel identificado no arquivo `evidencias/environment.json` |
| Node usado nas pequenas fixtures | 22.16.0; somente para demonstrar resolução de módulos sintéticos |
| Providers reais | Não executados nesta auditoria |
| Windows/WSL2 | Campanhas declaradas pelo projeto, não reproduzidas aqui |
| Server + Connector reais em dois hosts | Não executados |

Os pontos centrais foram verificados no ZIP e, para os trechos citados, confrontados com arquivos do mesmo commit por GitHub. Os hashes Git dos arquivos confrontados correspondem ao conteúdo local. As âncoras de linha deste relatório referem-se a esse snapshot, não ao HEAD futuro.

Não foram removidos gates de contenção para fazer a suíte passar. Nos testes dirigidos de autorização, apenas as dependências externas de qualificação/plataforma e os processos de provider são substituídos por peers controlados. Isso isola a fronteira sob teste e não qualifica um provider ou sistema operacional.

### 2.1. Preparação de dependências

A instalação por pip via rede não estava disponível por falha de resolução de nomes. Para reproduzir a dependência requerida, foi utilizado o código upstream exato de `rfc8785==0.1.4`, fora da árvore-fonte, com verificação dos hashes Git dos dois módulos. `jsonschema==4.26.0` estava instalado. A proveniência está registrada em `evidencias/dependency_provenance.json`.

A primeira execução completa teve duas falhas adicionais nos subprocessos dos exemplos, que não herdavam a dependência disponibilizada apenas por PYTHONPATH. A execução completa foi repetida em um ambiente de auditoria com essa dependência visível também aos subprocessos. Os números finais abaixo são dessa repetição. Não foi necessário editar o produto.

## 3. Resultados executados

| Campanha | Resultado | Interpretação |
|---|---|---|
| Suíte completa, repetição com ambiente de dependências corrigido | **644 PASS, 123 FAIL, 20 SKIP** | 787 casos; não foi uma suíte verde neste sandbox |
| API pública + arquivo C2 | **21 PASS, 1 SKIP** | Subconjunto da suíte completa; não somar ao total |
| Dentro desse subconjunto: 14 sementes nomeadas C2 | **14 PASS** | Confirma os cenários efetivamente presentes no arquivo atual |
| 14 sementes arquivadas da auditoria anterior, sem adaptação | **9 PASS, 5 FAIL** | Exigem interpretação de mudanças de API/fixtures; ver §5 |
| Novas regressões S01–S08 | **11 FAIL** | Oito grupos de problemas; nenhuma falha de setup nessa campanha |
| Repetição das novas regressões | **11 FAIL** | Mesmo comportamento, com XML xunit1 e sem warnings |
| Wheel e sdist | **Build concluído** | Backend setuptools, em cópia separada da árvore |
| Wheel instalado fora da árvore-fonte | **PASS** | Importação e recursos disponíveis |
| Consumidores isolados `embedded` e `remote` | **PASS / PASS** | São consumidores sintéticos do contrato, não a integração real dos três repositórios |
| Bundle NXL | **Verificado com `development-partial` explicitamente permitido** | Não comprova todos os cenários do protocolo |

Os XMLs são a fonte das contagens. A primeira execução completa, preservada para rastreabilidade, foi 642 PASS / 125 FAIL / 20 SKIP; duas falhas de preparação do ambiente foram eliminadas na repetição. A campanha API+C2 ainda emite um warning da fixture `_ClockLateNative.close` assíncrona usada em uma interface síncrona; isso não foi contado como prova de vazamento de processo do produto.

### 3.1. As 123 falhas não representam 123 bugs independentes

O ambiente não oferece a interface `/proc/self/task/<pid>/children` esperada pelo backend. As assinaturas da execução completa se distribuem assim:

| Assinatura | Casos |
|---|---:|
| Slots de processos retidos / capacidade Linux esgotada | 86 |
| Probe nativo sem confirmação de parada da árvore | 24 |
| Recusa explícita do preflight de contenção | 11 |
| Cenário de morte abrupta do owner / guardian | 1 |
| Teste que espera todos os requisitos de preflight disponíveis | 1 |

A classificação é por assinatura e dependências do ambiente. Não é uma demonstração de que cada um dos 123 casos passaria em outro host. A qualificação do backend precisa ser executada em Linux compatível e com evidência própria. Manter estado `unknown` e slots retidos pode ser a resposta correta quando não há comprovação de parada.

**Os achados S01–S08 foram reproduzidos separadamente e não dependem dessas 123 falhas.**

## 4. O que melhorou de fato

| Achado anterior | Situação nesta versão |
|---|---|
| R01 — leitura de recibo sob lock global | Os cenários de `get_receipt` retido e EOF foram corrigidos. A propriedade geral ainda falha nas operações de lease CAS: S04. |
| R02 — força no pool de dados | A força ganhou pool de controle separado. Saturar o pool de dados deixou de bloquear aquele teste. O novo pool também atende observação/close, que podem saturá-lo: S05. |
| R03 — guarda temporal | `send` ganhou consulta de relógio no despacho, e callbacks da factory são revalidados com relógio injetado. Persistem composição padrão, spawn enfileirado e aprovação: S01–S03. |
| R04 — replay de operação conhecida após EOF | Recibo idempotente voltou a ser retornado; não reproduzi a falha anterior nesse cenário. |
| R05 — fila ilimitada de notificações | Substituída por Condition e sinalização coalescida. O novo cenário sustentado passa. |
| R06 — raiz Pi e dependências | Raiz corrigida; pacote irmão irrelevante não altera o digest; parte das dependências passou a ser incluída. Arquivos efetivamente carregados ainda podem ficar fora: S06. |
| R07 — ABI/preflight | Consulta de subreaper corrigida e probe ativo colocado atrás do preflight. O novo erro corrompe o campo de código: S07. |
| R08 — discovery público | A composição pública passou a integrar Pi quando `pi_install_root` e `pi_node` são fornecidos. O teste atualizado passa. |
| R09 — DTO de resume privado | `CodexResumeGrant` público e anotação de environment corrigida; cenário de contrato passa. |
| R10 — callback retém adaptador | Cleanup agora cancela cooperativamente o sink e libera o adaptador; cenário anterior passa. Há recurso novo da factory sem fechamento público: S08. |

Também há uma entrada assíncrona `open_journal`, e a arquitetura de MCP HTTP direto foi preservada nas alterações inspecionadas. Não identifiquei reintrodução de MCP stdio nem de um proxy MCP no diff.

## 5. Como interpretei as cinco falhas das sementes antigas

Não seria correto tratar automaticamente as cinco falhas do arquivo arquivado como cinco bugs ainda existentes.

| Semente antiga | Interpretação |
|---|---|
| R03b / environment expira com relógio injetado | A factory agora levanta a recusa correta antes de iniciar. A fixture antiga não aceitava essa exceção e falha antes de sua asserção final. O cenário com relógio injetado foi corrigido; S01 testa o default e S02 a fila posterior. |
| R05 / `_wake` | A fixture acessa um atributo privado removido pela substituição por Condition. Não é persistência do vazamento antigo. |
| R06b / dependência resolvível | Permanece uma omissão real para formas de resolução não cobertas. S06 amplia a evidência com Node executando os arquivos omitidos. |
| R07b / monkeypatch no seam antigo | O gate foi movido/importado em outro ponto; a recusa ocorre. O defeito remanescente está no código de erro, testado diretamente em S07. |
| R08 / somente raiz confiável | O contrato público novo requer também os parâmetros específicos de Pi. O cenário configurado conforme esse contrato passa; não reportei isso como discovery ainda quebrado. |

O arquivo C2 mudou a fixture de dependência do Pi para declarar `package.json` e `main`. Isso é um caso válido, mas é mais estreito que a garantia de cobrir o código carregável da instalação. É necessário manter os casos adicionais, não apenas o formato que o novo algoritmo já suporta.

## 6. Achados confirmados

As âncoras abaixo são relativas a `src/nexus_connector_core/`.

### S01 — A configuração padrão desliga as verificações temporais da factory

**Prioridade:** P1. **Relação:** R03 / PC03 / PC06.  
**Código:** `composition.py:92–100`; `native/runtime_bridge.py:448–456`.

`create_runtime` passa `clock.monotonic` apenas quando o host fornece explicitamente um relógio. Sem esse parâmetro, passa `None`. A factory só verifica o deadline se o relógio não for `None`, embora o runtime possua seu próprio relógio padrão.

**Reprodução:** a operação começa válida; o callback de ambiente aguarda até o prazo real vencer; a composição pública padrão ainda chega a `connector.start` do peer. Foram usados o runtime, kernel, journal e factory reais. O peer é sintético e nenhum Codex real foi iniciado.

**Observação gravada:** `factory_clock_is_none=True`, `start_reached_after_expiry=True`.

**Correção:** criar uma única fonte temporal efetiva também no default e compartilhá-la entre runtime, kernel, factory e guardas de execução. Um parâmetro opcional de teste não pode habilitar uma proteção ausente na configuração normal.

**Aceite:** reproduzir ambiente/resume/ação nativa que atravessam o prazo, com e sem relógio fornecido. Nenhum spawn deve ocorrer depois de uma recusa comprovadamente anterior ao efeito.

**Teste:** `test_s01_default_public_factory_checks_expiry_after_environment`.

### S02 — A verificação de spawn continua antes da fila da thread

**Prioridade:** P1. **Relação:** R03 / PC03.  
**Código:** `native/runtime_bridge.py:542–550`.

A factory verifica `_revalidate_launch("launch")` e depois enfileira `connector.start` com `asyncio.to_thread`. A função executada pela thread não reavalia a autorização quando finalmente começa.

**Reprodução:** relógio fornecido e inicialmente válido; um worker único ocupado; `start` é enfileirado; o relógio avança de 100 para 161, com prazo 160; o worker é liberado e alcança `start`.

A guarda adicionada depois dos callbacks resolve uma janela, mas não cobre a espera posterior no executor. Não foi necessário explorar uma precisão de microssegundos: a espera foi controlada e a ordem demonstrada.

**Correção:** executar a validação dentro da unidade de trabalho que efetivamente inicia o processo, depois das esperas relevantes. Revalidar novamente quando houver outra espera antes da fronteira física. Preservar a distinção entre recusa antes do efeito e resultado incerto depois que o efeito pode ter ocorrido.

**Teste:** `test_s02_spawn_queued_in_worker_revalidates_when_worker_starts`.

### S03 — Resposta de aprovação nativa não usa a mesma guarda de efeito

**Prioridade:** P1. **Relação:** PC03 e controles de aprovação.  
**Código:** `native/runtime_bridge.py:242–279`; chamada superior em `runtime.py:576–599`.

`reply_native_approval` valida método, turno e disponibilidade antes do despacho. Mas não consulta `EffectFence` na escrita, nem no início da thread. A guarda do kernel superior também precede essa fila.

**Reprodução:** turno e pedido ativos; fence válido com prazo 160; resposta `accept` aguarda worker; o relógio passa a 161; ao liberar o worker, a resposta chega ao peer.

Não se trata de inventar uma aprovação humana ou responder a um pedido inexistente. O problema é uma resposta previamente autorizada produzir efeito depois de sua autorização temporal ter vencido.

**Correção:** incluir decisões permissivas e fornecimento de input no mesmo modelo de guarda de prazo, geração, turno e revogação. As ações de negar/cancelar/conter devem ter semântica explícita: não bloquear cegamente uma negação segura apenas porque se está impedindo uma nova autorização.

**Teste:** `test_s03_approval_reply_revalidates_at_delayed_native_write`.

### S04 — CAS de renovação e revogação continua sob o lock global

**Prioridade:** P1. **Relação:** R01 / PC01–PC03.  
**Código:** `runtime.py:1235–1279`, `1306–1329`, `1361–1374`.

As leituras de deduplicação foram deslocadas, mas `renew_lease` e `revoke_lease` ainda aguardam `cas_session_lease` enquanto seguram `self._lock`. Após o prazo e a tolerância, o watcher precisa desse lock para entrar na contenção.

**Reprodução:** journal real com uma barreira controlada somente no CAS; renovação/revogação inicialmente válidas; CAS retido; relógio avança além do deadline e da tolerância. Durante 1,6 segundo, a força física não é alcançada e o lock permanece adquirido.

A flag de expiração pode ser marcada em memória antes disso, o que é uma melhoria. O bloqueio confirmado é na entrada da contenção física. O timeout configurado de reconexão pode limitar a espera — no teste, cinco segundos —, portanto não afirmo que esse caso sempre bloqueia indefinidamente. Ainda assim, a contenção continua dependente da latência de outra operação de armazenamento.

**Correção:** retirar I/O das seções críticas de segurança, com reserva/revisão em memória e revalidação após o CAS. É indispensável tratar cancelamento depois de o trabalho ter sido entregue ao worker do journal: o commit pode acontecer mesmo quando o chamador deixa de aguardar. Não basta mover o `await` e atualizar o estado sem verificar corridas, revogação ou encerramento concorrente.

**Testes:** `test_s04_lease_cas_does_not_hold_global_containment_lock[renew]` e `[revoke]`.

### S05 — O pool de controle pode ser saturado por observações

**Prioridade:** P1. **Relação:** R02 / PC02 / PC11.  
**Código:** `native/runtime_bridge.py:339–389`, `420–425`.

O novo pool possui quatro workers e é compartilhado por força física, observação e fechamento. Separá-lo do pool de dados resolve a semente R02 original, mas observações ou closes travados podem consumir toda essa capacidade.

**Reprodução:** quatro peers ficam bloqueados em `observe_lifecycle`, ocupando os quatro workers; solicita-se força de uma quinta sessão. A força não alcança o peer enquanto as observações não são liberadas. O event loop permanece livre.

É uma falha injetada no backend de observação, não uma afirmação de que este ambiente reproduziu um deadlock de um provider real. O teste verifica a garantia arquitetural de despacho independente sob esse tipo de falha.

**Correção:** reservar capacidade de força não consumível por consultas de estado ou shutdown gracioso; coalescer observações e limitar sua fila. Prioridade em uma fila só não resolve workers já ocupados. Evitar threads ilimitadas. Caso o próprio backend de força fique preso no SO, reportar honestamente a limitação/unknown; não prometer uma garantia universal de morte.

**Teste:** `test_s05_observation_load_cannot_starve_reserved_physical_force`.

### S06 — A identidade qualificada do Pi omite código realmente carregado pelo Node

**Prioridade:** P2, impedir qualificação ampla com essa evidência incompleta. **Relação:** R06 / PC09.  
**Código:** `build_identity.py:145–179`, com composição em `90–128`.

A raiz foi corrigida e dependências declaradas são percorridas. Para cada dependência, porém, o algoritmo registra principalmente `package.json` e os arquivos declarados em `main`/`bin`. Isso não cobre todas as formas de carregamento suportadas pelas instalações Node.

Foram demonstrados três casos:

| Caso | Arquivo omitido que foi alterado |
|---|---|
| Resolução implícita | `index.js` de dependência sem entrypoint declarado |
| Import relativo dentro do pacote | `lib/value.js`, carregado pelo `index.js` já incluído |
| Campo `exports` | `entry.js` selecionado pelo manifesto |

Em cada caso, a fixture foi executada por Node 22.16.0 e passou a imprimir `v2` em vez de `v1`, enquanto `pi_build_identity` permaneceu idêntico. O binário representado no hash é uma fixture estável; a execução demonstrativa usa o Node instalado. Isso não qualifica o Pi real, mas comprova a omissão do algoritmo naqueles layouts.

**Correção:** definir uma cobertura completa e limitada do conteúdo executável do layout suportado — por exemplo, manifesto de conteúdo do pacote e dependências necessárias, ou bundle comprovadamente autocontido. Não assumir que `main` é o único arquivo executável de uma dependência. Recusar layouts não cobertos explicitamente em vez de qualificá-los por versão ou digest parcial. Alteração de semântica do digest requer versionamento e requalificação deliberada da allowlist.

**Testes:** `test_s06_qualified_identity_covers_code_node_actually_loads[implicit_index]`, `[relative_import]`, `[exports]`.

### S07 — Diagnóstico foi concatenado ao código tipado do erro

**Prioridade:** P2. **Relação:** R07 / PC06 / PC11.  
**Código:** `native/process/preflight.py:137–153`; `models.py:9–17`.

O primeiro argumento de `CoreError` é o campo `code`. O preflight monta esse argumento como `PROCESS_CONTAINMENT_UNAVAILABLE: <detalhes>`. O resultado não é um código estável acompanhado de uma mensagem: o próprio código muda conforme o diagnóstico do host.

**Reprodução:** preflight com `proc_children` indisponível. O código observado foi `PROCESS_CONTAINMENT_UNAVAILABLE: proc_children: unavailable`, em vez de `PROCESS_CONTAINMENT_UNAVAILABLE`.

Isso prejudica consumidores que precisam classificar exatamente a recusa, incluindo CLI, Server e mapeamento do protocolo. O gate físico existe e recusa; o defeito é no contrato do diagnóstico.

**Correção:** código constante e detalhes estruturados/redigidos em campo separado, com adaptação explícita do contrato se necessária. Testar a serialização nos consumidores, não apenas `str(exc)` ou busca por substring.

**Teste:** `test_s07_preflight_preserves_machine_readable_error_code`.

### S08 — O shutdown público não fecha o executor que sua factory criou

**Prioridade:** P2. **Relação:** ciclo de vida de R02 / PC06 / PC07.  
**Código:** `native/runtime_bridge.py:420–435`; `runtime.py:880–960`.

A factory é proprietária do novo pool e possui `close()`, mas `LocalRuntimeCore.shutdown()` não o chama. Na composição pública, o host não deveria precisar acessar `_native_factory` para liberar recursos criados internamente.

**Reprodução:** criar runtime pela API pública, ativar um worker do pool interno, executar shutdown sem sessões nem ownership incerto. O executor continua aberto. O teste faz o fechamento privado somente no seu bloco de limpeza, para não deixar recurso de auditoria pendurado.

Não foi demonstrado processo de provider ainda vivo nem vazamento por turno. O problema é ciclo de vida de threads: criação/shutdown repetidos podem reter recursos enquanto as instâncias continuarem referenciadas, sem depender de GC ou término do interpretador.

**Correção:** contrato público de propriedade/disposal com encerramento idempotente quando não houver trabalho ou ownership pendente. Não fechar cegamente a capacidade de contenção se ainda existirem sessões incertas que dependem dela. Testar tanto shutdown completamente resolvido quanto tentativas posteriores de reconciliação/força após um shutdown parcial.

**Teste:** `test_s08_runtime_shutdown_releases_factory_owned_control_pool`.

## 7. Precisão das evidências e encerramento C2

O documento `plans/correction-c2/evidence/R01-R10.md` afirma 14/14 sementes verdes, e isso foi reproduzido para o arquivo atual. Entretanto, as inferências gerais de algumas linhas precisam ser reabertas:

| Afirmação documental | Limite demonstrado |
|---|---|
| Nenhum await de journal sob o lock global | Ainda há CAS em renovação e revogação: S04. |
| Verificação na fronteira de spawn | Não cobre clock omitido nem fila posterior ao check: S01/S02. |
| Capacidade reservada para força | Existe, mas é compartilhada com operações que podem ocupá-la: S05. |
| Fechamento transitivo do build Pi | Percorrer dependências declaradas não cobre todos os arquivos carregados de cada dependência: S06. |
| Pool da factory disposto no lifecycle | Há `close()` privado, mas o shutdown do host não o aciona: S08. |

Não concluo intenção de manipular testes. O problema é extrapolar um cenário verde para uma garantia que tem outras entradas, defaults e filas. A rodada seguinte deve mapear cada afirmação a seus caminhos concretos e testes de falha, preservando os casos corrigidos.

## 8. Gate e ordem recomendada de correção

**Não ratificar E1 neste snapshot.** E0/preview pode continuar, sem tratar essa API como congelada nem promover o artefato a substituto operacional. E2 exige os consumidores reais; E3 inclui as demais capacidades previstas, como attach qualificado no escopo prometido.

| Ordem | Trabalho | Saída mínima |
|---|---|---|
| 1 | S01–S03, autorização transversal | Defaults e todas as escritas permissivas usam o mesmo prazo/geração na fronteira efetiva |
| 2 | S04–S05, contenção independente | Armazenamento, observers e close normal não atrasam a entrada física de força |
| 3 | S08 e S07, lifecycle/contrato | Shutdown público dispõe recursos resolvidos; erros têm códigos constantes |
| 4 | S06, qualificação Pi | Conteúdo realmente carregado coberto, sem perder portabilidade do build |
| 5 | Regressões e gate | 14 sementes preservadas, 11 novas passando, contratos/wheel e backend real do SO-alvo verificados |

Não contornar os achados duplicando adapters no Server ou Connector. Consumidores podem avançar em seus componentes independentes e registrar dependências, mas a correção deve continuar concentrada no Core.

## 9. Artefatos e o que não foi demonstrado

Wheel gerado: `nexus_connector_core-0.2.1.dev0-py3-none-any.whl`  
SHA-256: `74db042d5a003c10cd641c711df962013813415a18cf24ed4885f34bb066adb0`.

Sdist: `nexus_connector_core-0.2.1.dev0.tar.gz`  
SHA-256: `fcad1cb2772326719817a0e3266550981447bbe826562367ea4373ca862148c6`.

Manifesto NXL verificado: `sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630`.

O build utilizou o backend setuptools diretamente, com normalização das ferramentas do próprio projeto em uma cópia da árvore, pois `python -m build` não estava disponível. Isso demonstra geração/instalação e consumo dos recursos nesse ambiente. Não equivale à execução de um build isolado PEP 517 em toda a matriz, nem a uma prova de reprodutibilidade byte a byte entre plataformas.

Os consumidores `embedded`/`remote` são smokes sintéticos. Nenhuma conexão WSS real entre Nexus Server e Connector, provider real, campanha Windows ou WSL2 foi executada por esta auditoria. Os números desses ambientes nos documentos do projeto permanecem evidência fornecida pelo autor, separada dos resultados aqui reproduzidos.

O pacote da auditoria entrega relatórios, testes e logs. Não entrega um wheel corrigido ou uma mudança no repositório.

## 10. Evidências locais

- `RESULTADOS.json`: contagens e decisão estruturadas.
- `regressoes/test_review3.py`: 11 cenários de aceite executados e falhos no snapshot.
- `evidencias/review3_repeat.xml`: observações por teste, sem warnings na repetição.
- `evidencias/c2_and_public_api.xml`: API pública e C2.
- `evidencias/prior_and_c2.xml`: confronto com as sementes arquivadas.
- `evidencias/full_recheck.xml` e `.log`: execução completa com ambiente de dependências corrigido.
- `evidencias/full_recheck_failure_groups.json`: classificação de assinaturas.
- `evidencias/trechos_fontes.md`: trechos numerados e hashes Git do snapshot.
- `evidencias/integridade_fontes.json`: 332 arquivos originais inalterados.
- `evidencias/build.log`, `wheel_install.log`, `wheel_smoke.log`: build e consumo instalado.

**Conclusão:** há progresso sólido e correções válidas, mas os testes de fronteira ainda contradizem garantias necessárias a E1. Concluir essas garantias, sem alargar o escopo arquitetural, é o próximo passo.
