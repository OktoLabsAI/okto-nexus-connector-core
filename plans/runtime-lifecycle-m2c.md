# M2c — Native launch identity and Windows crash boundaries

2026-10-16. Technical checkpoint; M2 and UI-A remain open.

Managed Pi, Codex and Claude startup now uses the launch identity admitted with
the opening claim. The native factory holds the shared per-producer exclusion
gate, rechecks current authority, claims exactly once, and passes the planned
container identity to the platform adapter. Birth evidence must match that
identity. The retained startup task still owns a cancelled waiter's work.

Windows creates the named Job Object before its child and rejects malformed or
already existing names. Recovery observes/stops the exact planned job under the
producer fence without fabricating a birth record or using a historical PID.
Linux and macOS adapters accept their planned receipt/launchd identities. Their
unqualified crash boundaries remain conservative; this checkpoint does not claim
Linux/macOS recovery qualification.

The shared replacement-host helper checks the original opening generations and
requires a newer connection plus live authority. A fenced NEVER_CLAIMED proof can
settle its opening as FAILED. It preserves an already recorded possible-effect
marker and terminal fact; it never manufactures success, permits replay of a
possible effect, releases capacity, or changes another operation. Storage failure
rolls back settlement and retains the proof for another attempt.

Installed-wheel campaign: **159 passed**, zero failures/skips, Windows 11 AMD64,
Python 3.13.1; `pip check` passed. The runner used an isolated interpreter,
compared installed package bytes to the selected wheel, and excluded application
source from the import path. Includes existing runtime/receipt contracts, launch
admission/CAS/exclusion, all three synthetic native harness peers, settlement,
and real disposable Windows processes killed at five boundaries: after intent,
claim, container creation, spawn and birth persistence. Another case terminates
an unrecorded live child while its independent sibling remains alive. Capacity
stays reserved until the host handles the proven result.

- Wheel SHA256: `5042ca20a0fa9389f8749f5208701790e0f0d672f42bdb72334f05fe25375cf5`
- Local evidence: `build/process-launch-m2c-installed/manifest.json` and
  `build/process-launch-m2c-installed/results.xml`.
- Result SHA256: `8786ffe23a3f96141a5117150d3de80c4d87ee983c9d68c1cec1280e185ac636`.

The first settlement command accidentally selected the globally installed M1
package and failed collection; it was not an implementation test. The campaign
above installed and verified M2c explicitly.

Remaining M2: integrate consumer recovery/publication and distinguish a process
that never started from one observed stopped; qualify later handshake/receipt/ACK
crash boundaries and Linux/macOS containment. Never weaken monotonic receipt
rules or infer process absence from a missing birth. Global Nexus and both vendor
wheels still use M1 Core; no restart or provider qualification occurred for M2c.
