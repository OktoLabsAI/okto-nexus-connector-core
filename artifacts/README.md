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

Current: `nexus_connector_core-0.2.15.dev0-py3-none-any.whl`, SHA-256
4caa45add41da1fbc409316b90c34beafd60e3ea8a752c866071616af50f152a.
Adds pure R4 lease correlation and receipt reducers. The grant alone does not
authorize a native effect; Core application is a separate host step. The R4
bundle remains development-partial and R4_BUNDLE_EXECUTABLE=False.

Current: `nexus_connector_core-0.2.16.dev0-py3-none-any.whl`, SHA-256
`19b28e7f8f20c02032c32cd6b47f7d9e5b7f3b5b503c3e17620cc8ba6ee17946`.
Adds pure R4 attach and reconcile acknowledgment correlation. Control and lane
readiness still do not imply a productive Core session. The bundle remains
`development-partial` and `R4_BUNDLE_EXECUTABLE=False`.

Current: `nexus_connector_core-0.2.17.dev0-py3-none-any.whl`, SHA-256
`c35526cb347df56388ffae3fb3c3daf34745b8d48f01ff82c8116112409b7f`.
The closed R4 schema now covers 21 frame kinds. Pure event and approval
notification reducers preserve replay and scope facts. The hosts do not yet
execute R4 work, so the bundle remains `development-partial`.
