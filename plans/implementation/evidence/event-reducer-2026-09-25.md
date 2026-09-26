# K01.4 NXL event batch/ACK projection — 2026-09-25

`event_reducer.py` is a Core-owned pure producer/consumer component.
`event_batch_frame` emits a schema-checked batch of 1–128 contiguous events
from Core `RuntimeEvent` values. `reduce_durable_event_batch` tracks one
Server/executor/session/epoch stream after the host has durably committed and
deduplicated the batch. It holds gaps within a bounded 256-sequence window,
compares JCS event hashes for recent/pending duplicates, and advances only a
contiguous watermark. `event_ack_frame` can emit an NXL ACK only when that
watermark is positive. ACK means durable ingress, not UI delivery.

The reducer itself cannot prove a database commit. A host must call it only
after its transactional ingress succeeds and verify identity/hash for
duplicates older than the in-memory window against durable storage. Very old
replays and gaps beyond the window fail closed with `EVENT_GAP`, requiring
host reconciliation/replay rather than a speculative ACK. The projection is
not durable by itself and must be rebuilt or persisted by a consumer host.

Tests cover batch schema/contiguity, out-of-order gap closure, duplicate
conflict, namespace isolation, bounded history, invalid revision and parity
with the reference SQLite journal's contiguous watermark after each commit.
This is not yet full consumer conformance across Nexus and Connector.

Local development artifact SHA-256 values: wheel
`c7fbf7f1ceffc3146facc83403730f27ea108f2fc26877945991f9ea65b63231`;
sdist `7c834691928f66e4dbc5e2f28efb6fb7ef2210a2b8a7fc5464ad06de0dfa1cd8`.
