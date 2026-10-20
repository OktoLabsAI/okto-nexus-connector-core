# M4d4j: indexed pending-claim projection

The immutable `session_claims` history remains available for exact lookups and
auditing. A separate `reconciliation_pending` column and partial index select
only claims that still need a recovery report. New claims enter that projection
in the same admission transaction. `retire_reconciliation_claim` removes one
only with an exact opening-operation identity and a stable release ID/digest;
repeat calls with the same proof are idempotent and conflicting proofs fail.
Existing claim rows gain the pending default during journal migration.

The installed 0.0.12 wheel passed all 23 session-claim tests. A test with three
pending claims and 1k, 10k and 100k total rows observed 176, 106 and 106
SQLite VM steps, respectively, for the pending page. History pages still return
all claims; pending pages return only the three. These counts measure the
claim query, not complete Connector startup or filesystem audit.

The Connector must only retire this projection after a durable Server-accepted
release and must replay any interrupted cross-store checkpoint. Claims from
older journals start pending until such proof is applied; the historical
backfill is not yet qualified as an incremental maintenance operation.
