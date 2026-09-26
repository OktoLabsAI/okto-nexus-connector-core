# Handoff para Nexus Server e Nexus Connector

## 1. Responsabilidades

Este documento é preenchido pelo agente do Core após cada artefato incremental e consumido pelos agentes dos hosts. Não é uma autorização para o agente do Core editar outros repositórios nem uma mudança do desenho R3.

| Responsável | Entrega | Não deve fazer |
|---|---|---|
| Core | Factory/ports públicos, journal técnico/conformance, guards/containment, adapters, configuração nativa, schemas/manifest, wheel, matriz de capabilities. | Daemon operacional, WSS client/server, identidade canônica, inbox, MCP server/client/proxy. |
| Nexus Server | Contexto de agente autorizado, domínio, seleção local/remota, bindings lógicos, MCP HTTP direto, host local do Core e lado servidor do canal remoto. | Resolver filesystem remoto localmente, instalar Connector obrigatório para runtime local, copiar adapter/factory privada. |
| Nexus Connector | Daemon/CLI/serviço do SO, importação explícita da identidade de agente, vínculo local, secret store, canal remoto e host remoto do Core. | Criar usuários Nexus, outra inbox, proxy/fachada/servidor MCP, segunda implementação dos protocolos nativos. |

O Core pode oferecer mecanismos técnicos de journal e conformance que um host adapta ao seu armazenamento. O host continua responsável pela integração desse port, não por recriar a semântica de replay ou alterar unilateralmente o contrato.

## 2. Envelope de artefato a fornecer

Preencher `templates/HANDOFF_ARTEFATO.json` com valores reais, sem placeholders no handoff final. Campos mínimos: SHA do Core, versão da distribuição, nome/hash do wheel, hash de manifesto, revisão NXL/API, compatibilidade Python, schema do journal/migrações, callbacks obrigatórios, lifecycle do journal, capacidades qualificadas, plataforma/build, nível E0/E1/E2/E3, riscos e links de evidência. Nunca informar um SHA de exemplo como real.

Ambos hosts instalam o mesmo wheel/hash. Não pin de `main`, intervalo aberto de versão ou cópia local de schemas como referência final. Para código em desenvolvimento, um commit exato pode ser usado conscientemente, mas o gate de consumo deve verificar o artefato empacotado.

## 3. Alterações que os hosts devem absorver

| Mudança Core | Impacto esperado no Server | Impacto esperado no Connector |
|---|---|---|
| Journal worker/lifecycle assíncrono | Integrar startup/shutdown, não bloquear loop da API e não fechar store compartilhado por outra instância. | Integrar daemon start/stop e drain do worker; não abandonar request já enfileirado por timeout da CLI. |
| Factory pública | Substituir imports privados por composição suportada; runtime local sem Connector. | Mesma factory, com bindings/credenciais locais e canais remotos do app. |
| Guarda pré-efeito | Fornecer revisões/leases válidas e reagir a refusals/unknown sem replay. | Propagar fence corrente e respeitar grace/reconciliação; não renovar autorização por conta própria. |
| EOF/degradação | Expor estado indisponível e bloquear novas entregas ao endpoint afetado. | Não reiniciar turno/processo ao ver EOF; manter diagnóstico e contenção do Core. |
| IDs 1–160 + consulta legada | Gerar IDs válidos; oferecer consulta/autorização de legado sem alterar identidade ou reenviar. | Mesma política; não truncar IDs vindos do journal; handoff de diagnóstico se legado remoto precisar de envelope acordado. |
| Build versus binding | Consumir capabilities declaradas, não decidir plataforma por OS do Server para executor remoto. | Descoberta local aprovada; mudança de path revalida binding, build equivalente mantém qualificação pertinente. |
| Modelo efetivo | UI/API distingue solicitado/aplicado/observado; não afirmar confirmação inexistente. | Resolver configuração nativa pelo Core; não duplicar argv de cada provider no CLI. |
| Attach | UI/seleção explícita do alvo e escopo, sem promessa de adoção automática de conversa. | Detach sem kill de processo externo, sem autoattach pela primeira janela. |

## 4. Semântica mínima da composição

Os nomes novos de factory/opções serão definidos em PC06. Não copiar pseudocódigo como API já implementada. A composição pública final deve permitir a seguinte sequência por ambos hosts:

```text
carregar opções públicas e referências de recursos aprovados
  → abrir journal/ledger conforme owner declarado
  → compor runtime real pela factory pública
  → preflight das capabilities necessárias
  → discover/prepare com identidade, binding e root autorizados
  → open com operação idempotente
  → submit/control/events/inspect/reconcile
  → shutdown dos recursos próprios com relatório fiel
  → encerrar os stores que o host efetivamente possui
```

`shutdown` de runtime não significa apagar credencial/agente/histórico. O host não libera slot por conta própria. Um `CoreError.possible_effect=true` ou receipt unknown exige reconciliação; um timeout da interface que espera o receipt não cria uma nova operação automaticamente.

Callbacks mínimos devem ter ownership e budgets definidos: environment/secret refs limitados, contexto/capabilities autorizados, event sink não bloqueante do ponto de vista do Core, suporte restrito a ações Pi, decisão HITL validada pelo host e resume grant apenas onde demonstrado. Funções que rodam em worker não devem capturar event loop e usar objetos não thread-safe indiscriminadamente.

## 5. Pedidos de mudança de contrato

Quando um host necessitar campo/método não publicado, registrar: caso de uso, contrato atual, problema observável, mudança mínima, compatibilidade/migração, teste do consumidor e owner no Core. Não criar schema paralelo ou wrapper que conhece `codex app-server` para desbloquear sozinho.

Core decide/implementa o contrato comum e gera nova revisão quando necessária; ambos hosts atualizam explicitamente. Mudar default, limite, erro ou enum relevante precisa de changelog e teste, mesmo sem trocar assinatura.

## 6. Campanha conjunta e responsabilidade por bloqueios

| Campanha | Owner primário | Evidência exigida |
|---|---|---|
| Mesmo wheel em consumidores mínimos | Core | Wheel SHA, ambiente isolado e traces de composição pública. |
| Runtime local sem Connector | Server + Core | SHA Server, wheel, provider/OS e lifecycle completo. |
| Runtime remoto em dois hosts | Connector + Server + Core | Topologia, SHAs, wheel nos dois lados e ausência de provider/checkout remoto no Server. |
| MCP HTTP direto | Server + harness; Core configura | Configuração gerada, destinos de tráfego e teste tools-only independente do daemon. |
| Recovery de canal | Ambos hosts; Core aplica limites | Queda/reconnect/lease/receipts sem replay e estado incerto preservado. |
| Bridge Pi e handoff | Hosts de domínio + Core | Extensão versionada, ações tipadas e conclusão governada correta. |

Quando não houver outros repositórios/hosts/credenciais disponíveis ao agente do Core, executar o que é local e registrar o restante BLOCKED com artefato já pronto e owner. Não declarar teste conjunto como PASS nem paralisar todas as correções locais.

## 7. Rollout do consumo

Disponibilizar primeiro wheel development corrigido em ambiente de teste. Rodar consumidores mínimos, depois um provider local, depois o mesmo provider remoto. Só substituir a execução anterior no produto após gates P1, preflight real e reconciliação demonstrados. Manter capacidade de interromper o rollout sem apagar state; fallback para código anterior só quando formato/semântica dos dados permitirem.

Este roteiro não autoriza publicação externa, troca automática de versões de harness nem migração de credencial de agente.
