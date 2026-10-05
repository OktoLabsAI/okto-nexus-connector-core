# C7 lifecycle ordering — 2026-10-02

CI run 36951309175 at 85b25b8 exposed two test-ordering defects:

- Windows/Python 3.11, job 110664648507: W04 decline reached
  `SESSION_CLOSED`. The test advanced its clock beyond both the productive
  lease and the zero-length containment grace, allowing the supervisor to
  correctly close the peer before the negative reply.
- Linux/Python 3.11, job 110664648536: W03b observed the registered late
  handle before its asynchronous first force attempt ran (`force_calls == 0`).

W03b now waits for factory entry before cancellation and observer entry before
asserting the first failed force. It retains the bounded cleanup and second
public shutdown requirements. W04 explicitly covers the expired lease inside
the 15-second grace and the already-closed session beyond grace, with both
immediate and delayed decisions. Decline/cancel reach the live peer exactly
once inside grace; all replies to the closed peer remain forbidden. Accept
remains forbidden after productive expiry in every case. Production code and
default budgets are unchanged.

Validation: 19 passed in 33.58 seconds, Windows/Python 3.13, installed Core
0.2.52.dev0 wheel SHA256
`470eb23b28d917a3a154c2ef7cd9fdddf972ca6402c0668961b4c01909f1b732`.
Command: installed environment Python `-I -m pytest
tests/regression/test_c7_audit.py -q -o pythonpath=.
--junitxml=.../core-c7-ordering.xml`. The repository root is on the test import
path only for shared `tests.test_runtime` fixtures; Core is imported from the
installed wheel. Report: `c7-lifecycle-ordering.xml`.

An initial invocation without the test-fixture root failed collection; it did
not execute tests. Hosted CI for this correction remains pending. This is
synthetic lifecycle regression evidence, not native-provider qualification.
