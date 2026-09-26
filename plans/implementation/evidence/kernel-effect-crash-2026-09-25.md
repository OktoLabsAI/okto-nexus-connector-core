# K10.1 kernel effect-boundary crashes — 2026-09-25

`tests/fixtures/kernel_crash_peer.py` executes `OperationKernel` in a child
process and calls `os._exit(91)` at six boundaries: before/after the durable
possible-effect marker, before/after a synthetic external effect, and
before/after the `SUBMITTED` receipt commit. The effect writes and fsyncs a
single marker file in the test's temporary directory. After abrupt exit, the
parent reopens the journal and attempts the exact same operation ID/intent
with an effect that must never be called.

Windows and Ubuntu WSL2 tests show the durable stages: `RECEIVED_DURABLE`
before the possible-effect marker; `SUBMISSION_STARTED` after that marker
through the pre-receipt window, with `possible_effect=True` and
`retry_safe=False`; and `SUBMITTED` only after its receipt commit. The
external marker distinguishes a process death before and after the synthetic
effect, but it never causes automatic replay. This demonstrates the honest
uncertainty window without pretending the effect and SQLite commit are one
transaction.

The synthetic marker is not a harness spawn or pipe write. A second campaign
(`tests/test_owned_kernel_crash.py`) now combines `OperationKernel` with the
Core-owned process backend and a local LF protocol peer. The owner crashes
before spawn, after owned spawn/readiness, after a flushed but unterminated
stdin fragment, after an acknowledged complete command, or after the
`SUBMITTED` receipt commit. The fragment does not trigger the peer's command.
The parent holds a Windows process
handle or Linux pidfd before releasing the crash, then verifies that the
native peer exits, the SQLite stage remains honest, and duplicate admission
never invokes the effect again. The peer writes/fsyncs an exclusive marker on
its one accepted command, proving the post-write side effect was not replayed.
All five cuts pass on Windows and Ubuntu WSL2. This is a local protocol peer,
not a qualified Codex/Pi/Claude provider. Crashes inside the spawn primitive,
kernel-space partial writes, real provider ambiguity, saturation, disk-full and the
full OS matrix remain unqualified.
