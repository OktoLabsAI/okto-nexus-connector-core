# M4d4e1: bounded physical-registry head

The Core physical ledger now persists a deterministic SHA-256 chain over each
immutable journal registration. A registration and the head advance share one
SQLite transaction. Duplicate registration does not advance the head and a
failed batch rolls both back. The head includes the physical store identity,
last covered revision, digest and a `complete` flag.

A pre-existing registry starts with an incomplete head. The host can convert it
in batches of at most 128 registrations, resume after a crash, and only use the
head as a candidate audit frontier after conversion is complete. New
registrations during conversion remain in revision order and are picked up by
later batches. Reads validate that a complete head is at the registry's current
high-water revision. SQLite triggers reject updates and deletes of existing
registrations.

This is only a Core foundation. A host must bind the digest with an independent
store/nonce, finish its physical audit and define an anomaly policy before it
may omit its current startup directory scan. The chain does not attest that
files exist or prove native process termination.

Validation: 21 source and 21 installed registry/cost cases passed, including
1k/10k/100k registrations. The installed head read used 35 SQLite VM steps at
each size. Another 43 installed slot/capacity cases passed. The disposable
installed wheel is `okto_nexus_connector_core-0.0.12-py3-none-any.whl`, SHA-256
`2117495f1dd913634854116b557734ce96da081317a89149c5d6f8faf43a5090`.
Combined-host cases and real UI qualification are tracked in the Nexus ledger.
