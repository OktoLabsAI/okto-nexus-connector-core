# K04 bounded concurrent opens — 2026-09-25

`LocalRuntimeCore` now accepts a positive `max_concurrent_opens` (default 8).
The check and reservation happen under the runtime state lock before profile
revalidation, journal admission or native launch. When the limit is reached,
`open()` raises retry-safe `CAPACITY_EXCEEDED` with no possible effect and no
operation receipt. A finished open releases its launch slot whether it
succeeds or fails. The same operation ID can be retried after capacity frees.

`tests/test_runtime.py` holds one fake native launch in progress with a limit
of one, verifies a second launch is refused before admission, then releases
the first and successfully retries the second. Both sessions are included in
shutdown. The Windows source suite passes with 327 tests and 67 skips; Ubuntu
WSL2 passes with 382 tests and 12 skips (one expected legacy Pi fault-injection
thread warning). Wheel/sdist and clean-wheel verification pass.

This bounds simultaneous launch work, not all live or uncertain process trees.
Linux's owned-process backend has a separate 32-tree slot cap; a host-wide,
cross-platform process/unfinished-native-call budget with persisted uncertainty
remains K04 work.
