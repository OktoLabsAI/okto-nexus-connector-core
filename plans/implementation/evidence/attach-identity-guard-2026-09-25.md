# K08 attach target identity hardening — 2026-09-25

The Core-owned copy of the Claude cc-socks attach adapter now requires a
positive integer target PID, rejects a registry whose embedded PID differs
from the explicitly selected target, and lists only regular non-symlink
registry files whose name agrees with their embedded PID. This avoids
presenting an unrelated or substituted registry as the selected target.

Before sending, its PID-reuse guard now fails closed if the key directory
cannot be enumerated or if the pinned current key cannot be read. When
`procStart` was observed at bind time, disappearance of that field is treated
as identity drift rather than silently accepted. Those guard refusals are
before socket write; the existing cc-socks `sendall` remains ack-less and
ambiguous. The adapter still never adopts or kills the external process.

Targeted WSL2 tests exercise mismatched and boolean PIDs, symlink discovery,
unreadable key enumeration/read, and disappearing `procStart` alongside the
ported legacy attach suite. The full local suites passed with 404 tests on
Windows and 463 on WSL2; clean-wheel checks passed in both environments.
These tests use controlled local fixtures, not a
real Claude interactive target. Core's general managed-open factory still
rejects attach mode; scope-bound public prepare/open, lease-driven detach,
real-substrate qualification and the full TK-30/31/32 gates remain open.
