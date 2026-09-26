# K01.4 NXL receipt producer/consumer — 2026-09-25

`receipt_reducer.py` is a Core-owned, transport- and database-independent
producer/consumer component. `receipt_frame` emits a schema-checked NXL r3
`operation.receipt` from `OperationReceipt`. `reduce_receipt` validates every
incoming frame against the bundled contract and produces an immutable
projection. Its `observed` tuple contains only actual receipts, not inferred
ACKs or intermediate native stages.

Exact duplicates are idempotent. Lower out-of-order progress cannot regress
the projection. A terminal receipt can arrive directly after
`RECEIVED_DURABLE`; it need not wait for a lost intermediate ACK. An
`OUTCOME_UNKNOWN` receipt remains effect-possible and non-retry-safe until
fresh progress or terminal evidence resolves it. Conflicting identity, hash,
same-stage facts or terminal outcomes fail closed.
Because receipt frames have no per-stage revision, a later identical
`RUNNING` after an observed `WAITING_INPUT` cannot be distinguished from a
delayed duplicate; the projection conservatively remains waiting until new
distinguishable evidence or a terminal arrives.

Tests cover producer schema round-trip, absent intermediate ACK, uncertain
effect resolution, stale stages, duplicate/conflicting facts and invalid
contract input. This is a first part of the K01.4 kit, not yet a complete
consumer conformance/reducer suite for event streams, inventory and leases.

Local development artifact SHA-256 values: wheel
`7063c24aa6007cb8621ae68c088581310efdceb2f0f4fd5cef0c42d40d0ea535`;
sdist `d559454d0186ca053c62292054c11a0f2a6fbb97aabe912d5a6f9ac0bddcd36a`.
