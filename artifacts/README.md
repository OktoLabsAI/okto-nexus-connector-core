# Wheel de integração local

`nexus_connector_core-0.2.12.dev0-py3-none-any.whl`

SHA-256: `bd5326357608906bdd80ccefc3db4890137d9e8dc00935a88c5f6dd955bf9d8e`

Artefato histórico. Os wheels são distribuídos na branch de trabalho, sem
publicação em PyPI ou release.

`nexus_connector_core-0.2.13.dev0-py3-none-any.whl` é um preview Core R4,
SHA-256 `be0d974b036d6384e69655cff5556d6f5ee853f991a913087fe947c56fa2be96`.
Contém codec e schema R4 parciais, com `R4_BUNDLE_EXECUTABLE=False`; foi o
primeiro preview consumido pelo Nexus e Connector.

Current: `nexus_connector_core-0.2.14.dev0-py3-none-any.whl`, SHA-256
`759cdee946037ed5e215f901cdfb09b31baf350c7fde69e4d5f79bd41f515bee`.
Acrescenta payloads fechados de decisão/input, recibo/query escopados e
adapter IDs gerados do registry. `CONTRACT_REVISION` ainda é R3 e
`R4_BUNDLE_EXECUTABLE=False`; não autoriza efeitos remotos R4.
