# M4d4 — Physical journal registry foundation

Status: M4d4a registry foundation qualified. This is not an
audit frontier and must not be used to remove consumers' current startup scan.

`JournalLocationRegistry` is a storage port for immutable physical creation
intent. Its SQLite adapter lives in the existing installation slot ledger.
Locations explicitly distinguish a per-session journal from a shared-host
journal. Only portable, non-reserved basenames are accepted; no wire paths or
native ownership claims are added.

Registration occurs in atomic batches of at most 128. An exact retry returns
the original revision. A filename/scope reassignment rejects the entire batch.
Revision-bounded pages exclude concurrent later registrations and exact lookups
do not enumerate history. Registration does not create a journal file, consume
capacity, prove an audit or authorize native execution/release.

Source tests cover reopen/idempotence, transactional conflict rollback,
high-water paging, two storage connections racing one identity, cancelled
observers with a retained storage worker, portable-name constraints and
transaction rollback when storage is full. The 37-case final source campaign
passed. **44 installed cases passed** in 14.34 seconds with exact package-byte
verification and unchanged test inputs. Dependencies passed `pip check`.

The first isolated environment lacked `rfc8785` because user-site dependencies
are excluded by `-I`; that pre-test import failure was corrected by installing
the wheel's declared runtime/test dependencies in the isolated environment.
The final run used `build/m4d4-registry-env` with system-site dependencies,
`-I`, and the exact Core package installed in that environment. No application
source directory was added to the test interpreter.

Wheel SHA256: `e93dc1e1cdcc5d0868265c36c0e1200a1ff048aa79371e410727b3dfe74cad3b`.
Evidence: `build/runtime-lifecycle-m4d4-registry-installed/{manifest.json,results.xml}`.

Host adoption, first-audit conversion, store/restore identity, frontier
invalidation, large-history storage-budget measurements and the coordinated
UI gate remain pending. The canonical design is Nexus's
`plans/runtime_lifecycle/m4d4-store-audit-design.md`.

The M4d3 installed campaign continues using its frozen Core artifact
`fffcfad6a82a67fb4b9cc4b25b0718a3c3e30bf119dde71ee07dcb062b814898`.
This foundation has not replaced that consumer artifact or the global installation.
