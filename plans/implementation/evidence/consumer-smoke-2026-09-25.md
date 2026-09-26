# K11 independent clean-wheel consumer smokes — 2026-09-25

`tools/verify_wheel.py` installs the current wheel in a temporary virtual
environment, runs with Python isolated mode from that temporary directory,
and now executes two separate application-free consumer processes from
`tools/consumer_smoke.py`:

- `embedded` prepares and opens an injected native session through the public
  `LocalRuntimeCore` facade and `SQLiteJournal`, submits and deduplicates a
  turn, inspects ownership, closes and shuts down without a product daemon.
- `remote` pins/verifies the installed development-partial NXL bundle and
  round-trips a receipt frame plus a durable event-batch/ACK projection.

Both processes run in Python isolated mode and assert that the imported Core
package lives under the temporary environment's prefix. The verifier traces
both runs to its single installed wheel SHA-256; neither imports Nexus Server,
Connector or a sibling checkout.
The smoke source is included in the sdist so the verification path can be
reproduced from the source artifact. Clean-wheel checks passed on local
Windows/Python 3.13 and Ubuntu WSL2/Python 3.12.

This is a synthetic consumer smoke, not the TK-43 requirement that the real
Server and Connector pin and run the same Core wheel. It does not prove real
network transport, host-durable event ingress, provider qualification or the
protected publication workflow. Those remain open.
