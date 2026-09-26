# K01.4 NXL inventory producer/consumer — 2026-09-25

`inventory_reducer.py` is a Core-owned, pure NXL r3 producer/consumer
component. It emits schema-checked `inventory.snapshot` and
`inventory.delta` frames from immutable candidate records and reduces them
to an immutable Server/executor-scoped projection.

The delta frame has no base-revision field. The reducer therefore requires
`inventory_revision == current + 1`; a gap needs a newer authoritative
snapshot. A snapshot with the same revision and same candidate set is
idempotent; a conflicting same-revision snapshot fails. Exact semantic delta
duplicates are idempotent, while changed same-revision facts fail closed.
Unknown removals fail closed rather than silently assuming a candidate was
present. Stale lower revisions cannot roll back the projection.

Tests cover schema round-trip, revision gaps and snapshot repair, updates,
removals, reordered duplicates, conflicting revisions, scope mismatch and
invalid candidate/frame input. Native discovery and consumer-host integration
remain separately unqualified; this is not the full K01 conformance gate.

Local development artifact SHA-256 values: wheel
`3b14d1ff21e52a0abdebe4880b06852423fb81b057edee185ee06f9a9be26f81`;
sdist `de94f0c3a8f0f9e5cf4530622315df8099f01f4bd2a41b6c3275aa4379891cf6`.
