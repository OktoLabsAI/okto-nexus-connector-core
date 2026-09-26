# K01.4 NXL lease request/grant projection — 2026-09-25

`lease_reducer.py` is a Core-owned pure producer/consumer component for
`lease.renew` and `lease.granted`. It validates both frames with the bundled
NXL r3 schema, correlates scope, lease ID, authorization revision and expected
session-owner generation, then calculates a conservative monotonic deadline
from the request's send time, not the grant's receive time. RTT therefore
cannot lengthen the local lease. `lease_active` gates only local time/boot and
revocation; it is not sufficient authorization for work.

NXL r3 does not echo `connection_generation` in `lease.granted` and has no
separate renewal-request ID. This implementation treats `lease_id` as a new,
unpredictable, host-issued identifier for **each** renewal attempt and
requires an exact echo. Replaying the same grant returns the old projection
without extending its deadline; a changed grant for the same ID conflicts.
The host must never reuse IDs, must retain/rebuild the projection across the
active process lifetime, and must authorize requests. This convention needs
agreement in both consumers before declaring the contract normative.

A new grant after expiry, reboot/boot-ID change, owner-generation change,
stale connection or authorization revision, or revocation requires external
reconciliation/revalidation. Heartbeat is not treated as a work-lease renewal.
Tests cover frame round-trip, conservative deadline/RTT, replay, new renewal,
scope and generation mismatch, reboot, expiry, invalid times and revocation.
No real Server/Connector exchange has been qualified yet.

Local development artifact SHA-256 values: wheel
`a838e2f0689aa28849340825c3130190b0ba294c0840cd1d34d6e9dc03303200`;
sdist `4c6ec5357240377efa3072307cc410ba473bdf66170e55a25e8426dd1df00b79`.
