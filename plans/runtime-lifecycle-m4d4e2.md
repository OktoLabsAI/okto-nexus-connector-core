# M4d4e2: Core side of the audit handshake

The physical Core ledger can now durably stage an `audit_<32 hex>` nonce
against its exact, complete registry head. The nonce, revision and digest live
in the same SQLite ledger as the journal registrations. The host supplies the
nonce only after its own physical audit; Core rejects an incomplete or stale
head. Repeating the same request is idempotent. A later registration advances
the head without silently changing the staged anchor.

The host must commit its own copy of the nonce, store identity, revision and
digest in independent storage before this becomes a cross-store handshake.
Crash between Core staging and host commit means no usable host frontier and
requires another physical audit. A host also needs a bounded delta check and
background anomaly policy before bypassing its current startup directory
scan. This checkpoint changes no host admission behavior.

Source verification: 32 registry and slot-ledger cases passed, including
incomplete legacy conversion, stale-head refusal, staging idempotency,
post-anchor registration and reopen. Another 35 installed registry, 1k/10k/100k
cost and slot-ledger cases passed. The disposable installed wheel is
`okto_nexus_connector_core-0.0.12-py3-none-any.whl`, SHA-256
`19e1e8e4cc78f9d2ac882c858b2866bb1b22e5eba46009601a88796578fd3721`.
Combined-host validation and the other half of the handshake remain pending.
