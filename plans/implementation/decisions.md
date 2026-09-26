# Decisions and current limitations

- ADR-001: exact NXL revision r3 is required in development. A shared wire
  major does not imply compatibility with the r1 draft.
- ADR-002: intent hashing uses the pinned, pure-Python `rfc8785==0.1.4`
  dependency for RFC 8785 canonicalization, including ECMAScript number
  formatting and UTF-16 property ordering. Core rejects non-finite values,
  unsafe Python integers, unsupported JSON types and duplicate parsed keys.
  The dependency is Apache-2.0 and is not copied into this repository.
- ADR-003: after `SUBMISSION_STARTED`, a crash or lost result leaves possible
  effect. The kernel returns the existing receipt on duplicate operation ID
  and never invokes the effect again. A later reconciliation requires evidence.
- ADR-004: SQLite is local technical storage only. The implementation has a
  contiguous event watermark and transactional event item/payload budgets,
  plus explicit durable-ingress ACK and bounded compaction of ACKed event
  bodies. SQLite file/WAL byte bound, automatic maintenance and a
  cross-process writer lease remain open; it does not qualify as the complete
  K04 journal.
- ADR-005: the dependency-free `native` helpers are exact source copies and
  remain private. Selected legacy assertions were adapted; the full legacy
  suites have not yet run against this package.
- ADR-006: four legacy native connectors were copied into the Core wheel with
  their application imports replaced by local compatibility types. Synthetic
  peer tests establish selected protocol parity. A private bridge maps their
  synchronous API into the public async runtime; real version qualification
  and full legacy/provider campaigns remain. No import or runtime path refers
  to the Nexus checkout.
- ADR-007: historical Nexus version allowlists are metadata only. The new
  wheel's effective qualification sets are empty until provider/platform
  campaigns execute. A future grant is keyed by exact native kind, version,
  real platform, parsed architecture and binary fingerprint. A version string,
  read-only probe or synthetic peer cannot enable `managed_work` or native
  approval capabilities on its own.
