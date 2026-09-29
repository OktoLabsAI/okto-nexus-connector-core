# NXL R4: bundle de desenvolvimento

Core `0.2.13.dev0` inclui uma revisão R4 separada de R3 em
`contracts/nxl/r4`. O gerador autoral é `contracts/generate_r4.py`; o
manifest verifica o schema embarcado por SHA-256. `decode_r4_frame` e
`encode_r4_frame` rejeitam JSON ambíguo, revisão incorreta, campos extras,
payload de abertura com executable/argv/env e ausência de owner/grant.
`r4_submit_intent_hash` usa domínio da revisão R4 e não altera hashes R3.

O bundle atual cobre `binding.attached`, `reconcile.accepted`, os três
frames de lease e `operation.submit` com open/submit/steer/interrupt/close.
Seu status é `development-partial` e `R4_BUNDLE_EXECUTABLE` é `False`.
Faltam os frames alterados restantes, approval/input, reducers e efeitos
de runtime antes de aceitar R4 em uma conexão. `CONTRACT_REVISION` continua
R3; consumidores devem manter execução remota bloqueada.

O artefato wheel `nexus_connector_core-0.2.13.dev0-py3-none-any.whl` tem
SHA-256 `be0d974b036d6384e69655cff5556d6f5ee853f991a913087fe947c56fa2be96`.
No wheel instalado via `python -I`, o manifest R4 retornou SHA-256
`d234ce45717d21610835ef1cd58dbf4099120efd9bbae69dd5ef0a9e83280094`
e `executable=false`. Cinquenta e quatro testes direcionados de R3/R4,
inventário e descoberta passaram. Nenhum teste de provider ou multi-host
foi inferido desse resultado.
