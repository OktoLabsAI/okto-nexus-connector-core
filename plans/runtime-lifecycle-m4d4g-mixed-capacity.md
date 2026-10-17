# M4d4g: mixed physical registry and capacity history budget

The earlier 100,000-location measurement used 43.9 MiB of the Core slot
ledger's 64 MiB default, without capacity history. A disposable benchmark now
registers one canonical physical journal location and persists one terminal
no-effect `new_session` capacity reservation per session through the public
Core ports. No journal payload, native process or Nexus database is created.
It uses 36-character identities and unique attempt/affinity values.

| Paired records | Registry bytes | Mixed ledger bytes | Capacity increment |
| ---: | ---: | ---: | ---: |
| 1,000 | 561,152 | 2,666,496 | 2,105,344 |
| 10,000 | 4,546,560 | 25,755,648 | 21,209,088 |
| 100,000 | 44,011,520 | 256,573,440 | 212,561,920 |

The 100,000-case ran with an explicit 512 MiB ceiling and completed in
330.608 seconds of registry and capacity writes. Its 256.6 MB allocated
database is 3.82 times the former 64 MiB ceiling. The Core default is now
512 MiB, so the same representative history fits with approximately 280 MB
headroom. SQLite's `max_page_count` is a growth ceiling, not a preallocation.
The benchmark still has a finite limit and refuses invalid settings; it does
not claim that every permitted identifier size or unlimited history fits.

Fifteen selected slot-ledger, capacity-cancellation and physical-registry
tests passed from source and the same fifteen passed from the built wheel in
a separate environment importing Core from `site-packages`. The installed
wheel reports a 536,870,912-byte default. Wheel SHA-256:
`55b58a13f7112e63a44a08efb787ca5e43128f4d090fd639a7a9b307e5e43ecd`.
The test environment reused third-party dependencies already installed on
the machine; this was not a clean dependency-resolution campaign.

The budget change prevents premature storage exhaustion at this measured
history size. It does not replace lifecycle-safe retirement of terminal
capacity records, qualify arbitrary longer histories, or prove real-host
latency. The global Nexus remains stopped; M4's installed cross-component and
real UI gate remains open.
