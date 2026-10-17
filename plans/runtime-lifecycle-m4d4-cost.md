# M4d4 — Physical registry cost qualification

Three cases passed against the installed M4d4a wheel, with exact verification
of all 160 package files and unchanged test inputs. No product code, default
budget or wheel changed. The test registers through the public port in batches
of 128; no session journal or native process is created.

| Registered locations | Allocated SQLite bytes | Exact lookup VM steps | 128-row page + snapshot | Tail page |
| --- | ---: | ---: | ---: | ---: |
| 1,000 | 536,576 | 17 | 1,322 | 22 |
| 10,000 | 4,513,792 | 17 | 1,322 | 22 |
| 100,000 | 43,925,504 | 17 | 1,322 | 22 |

Names follow Nexus's hashed session layout; server, executor and session IDs
are 36 characters. Allocated bytes are SQLite page count times page size,
including empty ledger/capacity schema and registry indexes. WAL size and
wall-clock latency are not treated as deterministic limits.

The 100k registry consumes about 41.9 MiB of the default 64 MiB ledger budget,
leaving about 22.1 MiB for other ledger data. This is **not** proof that a full
host with 100k retained capacity operations fits that budget, nor that maximum
allowed identifier lengths have the same cost. Audit/retention design must
account for combined metadata before adopting its default. Storage-full
retention is covered separately by the M4d4a qualification; the budget was not
silently raised to make this measurement pass.

Reports: `build/runtime-m4d4-registry-cost-installed/{manifest.json,results.xml}`.
Pytest emitted three `record_property`/xunit2 format warnings; the properties
are present and were inspected in the generated XML. No case failed or skipped.

Wheel SHA256:
`e93dc1e1cdcc5d0868265c36c0e1200a1ff048aa79371e410727b3dfe74cad3b`.
Full audit frontier, restore detection, mixed-history budget and UI gates remain
open in the Nexus plan.
