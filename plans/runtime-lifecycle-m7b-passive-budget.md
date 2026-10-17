# M7b: budget passive Pi identity readers

The Pi inventory observer periodically verifies a declared dependency closure
of about 14,097 files on the local Windows installation. A read-only profile
measured one complete content identity at 13.185 seconds under the earlier
four-reader setting. The production Nexus remains on its prior installed Core.

This checkpoint gives passive discovery two file readers while an admitted
runtime opening retains four. It does not cache completed hashes, reuse a
stale identity, skip a file, change the build-identity algorithm, or relax the
pre-spawn validation. The observer still joins its readers on cancellation.
The two budgets are selected by the existing cancellation scope carried by
passive discovery; direct launch validation has no such scope.

The focused tests compare the two paths' exact identity, hold readers to
verify their concurrency budgets, and cancel a passive scan while reads are
in flight. The selected source campaign passed 100 tests; the same 100 tests
passed from the built wheel installed in a separate virtual environment. The
installed import resolved to that environment's `site-packages`, with the
passive budget of two. The wheel is
`okto_nexus_connector_core-0.0.12-py3-none-any.whl`, SHA-256
`d9cf577731e123c417eb731c6b34b5e6fa208be7f33d86441e426c8fedadc1e8`.

The host was under concurrent load from an unrelated application when this
checkpoint began, so it does not claim a latency improvement or qualify UI-B.
That gate will measure installed, real-agent behavior at the larger M7
milestone. The Nexus production instance was left stopped after the operator's
request; no global runtime was changed by these tests.
