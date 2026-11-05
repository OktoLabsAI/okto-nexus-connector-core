# R3 service-definition increment

Pure Windows user-service specification/renderer and native-export fingerprint
added for reuse by Nexus and Connector. No database, Server policy, credentials
or OS effects are introduced into Core imports. See `docs/user-service-definitions.md`.

13 tests passed, including actual Windows Task Scheduler syntax validation via
TASK_VALIDATE_ONLY, with task absence checked before and after. Evidence XML
lives in the Nexus fixed-plan ledger as
`plans/agent_ops/evidence/pr02-core-service-definition.xml`.

This is a definition contract, not installed-service or login qualification.
Host ownership/CAS, supervisor controls, drain policy and consumer integration
remain in progress under SVC-05/06/07/09/12.
