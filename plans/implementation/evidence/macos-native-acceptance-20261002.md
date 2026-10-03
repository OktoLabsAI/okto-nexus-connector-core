# Native macOS Intel acceptance — launchd coalition backend — 2026-10-02

Campaign: `tools/macos_native_acceptance.py --runs 100` (script SHA-256 in
the retained JSON, matches the committed file). Host: Intel x86_64,
macOS 26.4.1 (25E253), Python 3.12.4, GUI login session (`gui/501`).
Report: `macos-native-acceptance-intel-20261002.json`. Status **PASS** in
92.0 s with fd-delta 0.

This exercises the production backend (`OwnedDarwinPopen`, the launchd
guardian and the coalition census in `nexus_connector_core.native.process`),
not a probe prototype. Synthetic Python fixtures only; no provider,
credential or workspace code ran (`provider_execution=false`).

| Scenario | Result | Key numbers |
| --- | --- | --- |
| double-fork/setsid escape ×100 | PASS | 100/100 proven stop (proof D), 0 survivors, 0 census misses, 0 label leaks; avg 0.40 s, max 0.44 s per case |
| owner SIGKILL ×3 | PASS | guardian drained the coalition to zero after owner death in 3/3 |
| cancellation escalation | PASS | SIGTERM delivered and ignored, escalated to SIGKILL (rc −9), proven, 0 survivors |
| descriptor hygiene | PASS | leader and grandchild report no extra fds; received SCM_RIGHTS fds non-inheritable; stdin/stdout round trip; separate stderr |
| shared-coalition refusal | PASS | guardian exit 126 with `coalition_refusal` before any native spawn when its pair shares a type with the caller |
| census overflow | PASS | 66 live members (leader + 64 children + setsid orphan); limit 16 → 16 pids + overflow; limit 256 → all; proven drain |
| slot retention | PASS | 32 slots held, 33rd refused ("capacity exhausted"), proven stop released one, replacement accepted |
| PID churn | PASS | rapid fork/exit churn during stop; proven, 0 survivors, no incomplete scans |
| SIGSTOP race | PASS | self-stopped members reached by SIGKILL; proven, 0 survivors |
| normal exit | PASS | leader exit code 7 propagated; surviving grandchild drained after proof |

Stop-proof design implemented and validated: per-PID census membership,
birth revalidation, coalition revalidation, `SIGSTOP` interlock (a stopped
member cannot fork/exec/exit), post-signal birth re-read (a recycled
target is reported as `suspect` and refuses the proof), and two
consecutive *complete* empty censuses. Other-uid processes are EPERM and
skipped as foreign (matching the qualified probe evidence), except a PID
previously seen as a member whose death was not confirmed — kqueue
`NOTE_EXIT` watchers confirm member deaths so recycled PIDs are
distinguished from a real setuid-transitioned member, which blocks the
proof instead of fabricating a stop.

## Test-suite status on this host

Full suite (installed 0.2.57.dev0): **1205 passed / 42 skipped** with one
deselection, versus the pre-implementation darwin baseline of 132 failures
(owned-process paths were unqualified). `test_owned_process` generic
contract now runs on darwin.

`test_native_runtime_bridge.py::test_copied_peer_terminal_reduces_public_receipt`
(the `[claude_stream]` param) was already failing in the darwin baseline;
with the backend it passes its assertions but can hang at interpreter
exit. Root cause (diagnosed with stack dumps, retained below): the claude
start path performs two sequential owned version probes, so the producer
outlives the runtime's session lifecycle by seconds at darwin's ~0.3–0.5 s
launchd bootstrap latency; the runtime/adapter abandon the connector
without `close()`, the native stays alive, the events() worker waits on a
condition only `close()`/EOF would set, and the asyncio executor join at
loop close blocks forever. A related genuine hole was fixed in
`runtime.py::_contain_late_open` (a late native completing after its
binding closed is now contained instead of dropped), but the full fix
requires bounding that worker/close path in shared runtime code and is
deferred to avoid altering Linux/Windows behavior in this increment.

## Qualification scope and open limits

- Qualified: this one Intel host, macOS 26.4.1, GUI login domain, Python
  3.12.4, synthetic fixtures through the production backend.
- Not qualified: Apple Silicon, other macOS versions, headless/SSH
  sessions (passive preflight reports `session_domain` unless
  `launchctl managername` is `Aqua`; user-domain bootstrap was refused
  natively, error 5), real providers, Connector IPC and Nexus UI, hosted
  CI.
- Known residual limits (documented in the guardian): a descendant that
  execs a setuid binary becomes unreadable/unkillable; an unconfirmed
  EPERM transition of a seen member blocks the proof forever (guardian
  stays alive holding ownership) except when death was watcher-confirmed.
  Observer-crash label removal (autonomous job lifecycle) remains a
  separate acceptance item: the observer removes labels on normal stop,
  failed startup and proven stop; a crashed observer leaves the label
  registered (the guardian still drains the tree, verified above).
