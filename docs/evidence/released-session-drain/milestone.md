# Released session evidence during cooperative drain

A normal close could stop the owned process, release its slot and evict the
runtime entry, while its original reconciliation claim remained in the journal.
Drain then treated that claim as orphaned and stayed UNKNOWN despite locally
confirmed release. The real M1 campaign exposed this sequence.

The bounded local tombstone now retains the exact opening, epoch and owner
generation proof. Drain and same-journal composition use that proof only for
the matching claim resource, with revision and unique-owner fences. Other
operations, ACKs, producers, late handles and release obligations still block.
No receipt, claim or ACK is rewritten. Missing or ambiguous identity, lost
proof after restart and bounded-proof eviction remain UNKNOWN.

The final 59 unique cases passed both source and installed qualification,
including 24 new cases. The three earlier fixture failures are preserved and
are not counted as qualification. All 166 package payloads match frozen source,
wheel and installation. Six pre-existing Ruff findings are unchanged.

The candidate wheel SHA-256 is
`4e677a205f5a486ef7134b8411983420c1c763c3dda274128a9c623ad1b1775d`.
The Nexus host regression separately changes from pending to DRAINED without
force while preserving its historical claim, receipts and ACKs. Consumer
qualification and pins are maintained in the Nexus campaign ledger.

No live M1 process was changed, no provider was called, no migration or protocol
authority was added, and this artifact is not a published release.
