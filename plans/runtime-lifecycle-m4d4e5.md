# M4d4e5: reject a definite physical-ledger rollback

Core exposes one pure rule shared by Nexus and Connector: when a host has a
stored audit anchor, a missing Core anchor, an incomplete head, a lower Core
revision or a different digest at the same revision fences native admission
with `PROFILE_DRIFT`. A head ahead of the host remains possible after ordinary
new registrations or a crash between staged and host commits; the host still
runs its full physical audit before pairing a new token.

This catches a definite same-identity partial restore. It does not prove that
an ahead Core head extends the host's older digest, and it does not permit
skipping the startup scan. Both need the bounded delta and background anomaly
protocol before an optimized startup can be considered.

The 21 registry tests passed from source and the installed wheel. The
disposable wheel SHA-256 is
`daaa8d08301b387bd96af1487d418bb6458f4c1411f221cddfc2c3903d78dd5c`.
