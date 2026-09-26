# Durable session-lease fence (K04) — 2026-09-26

Closes the "durable current-owner CAS" part of the K04 reconnect/ownership
gap. `runtime.open` now seeds a `session_lease_state` row atomically with the
session claim whenever the opening admission carries the
authorization/configuration revisions (the kernel supplies them from the
launch `ExecutionContext`). `renew_lease` and `revoke_lease` advance that
row through journal compare-and-set **before** the in-memory generation
changes:

- CAS matches the current connection generation and enforces monotonic
  component updates; a stale expected generation, a non-monotonic update or
  an attempt to un-revoke fails `STALE_GENERATION` without change.
- A legacy claim without lease evidence fails renewal/revoke with
  `SESSION_UNKNOWN` — a durable fence is never seeded from memory after the
  fact.
- A revocation committed durably can never be revived.
- A second Core instance sharing the journal (or a host-side CAS on the same
  file) that advances the row makes an older in-flight renewal lose with
  `STALE_GENERATION` without the losing generation ever becoming active.
- A crash between the durable revocation and the in-memory update leaves a
  durably revoked lease, never a revoked session whose row could still be
  renewed.

Public surface: `SessionLeaseState` export and
`LocalRuntimeCore.persisted_lease(session)` — the durable last-known fence
for host reconciliation after restart. It is evidence, not process liveness,
not a lease deadline and not takeover authority. The Journal port gained
`cas_session_lease`/`get_session_lease`; the reusable conformance kit now
requires them (seed-with-claim, CAS update, stale/non-monotonic/revive
rejections, legacy-claim behavior, reopen persistence, restart continuation),
and the faulty host-adapter detection tests cover the new admission
arguments.

This does not implement physical process takeover: ownership after restart
still requires host reconciliation (birth observation, slot inventory,
claimed sessions); the lease row only fences generations and revocation
durably.

Verification (all local, `rtk`-prefixed):

- `tests/test_session_lease_state.py` (5 tests: journal seed/CAS/reopen,
  second-connection fence, bad-value rejection, runtime
  open/renew/revoke/restart, runtime renewal losing to a peer-moved durable
  fence) plus the extended conformance kit pass in each local
  Windows/WSL2 × Python 3.11/3.12/3.13 environment (focused runs).
- Full Python 3.13 suites: Windows 607 passed/73 skipped; WSL2 666/14, each
  with the known injected legacy Pi warning.
- Normalized builds byte-identical across Windows/WSL2: wheel SHA-256
  `1e811d1961072af56ed1d16a0c0f036300c78b4350af3c7db427be7378e20682`,
  sdist SHA-256
  `55688e70278f1e36cb1c7fca373fb3a15a1c546f0adb677b9689706e3a2bc9b5`.
  Strict Twine, development release validation (`publishable:false`) and
  offline wheel/sdist installs with both consumer smoke roles passed on
  Windows and WSL2 Python 3.13.

Hosted CI remains blocked externally: every push starts `Core CI`, but
GitHub refuses to start the jobs ("recent account payments have failed or
your spending limit needs to be increased") — a billing fix in GitHub
settings is required before the hosted matrix can run.
