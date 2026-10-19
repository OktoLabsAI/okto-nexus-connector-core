# M2g — durable Darwin guardian stop proof

2026-10-19. Implementation checkpoint; full Core matrix still running.

The launchd guardian previously sent its `D` stop proof only through the
observer's AF_UNIX channel. After an owner crash the new owner had no durable
way to distinguish a drained coalition from a live tree, so a claimed launch
remained `CONTAINER_UNCERTAIN` even after physical cleanup.

The owner now creates a private, identity-bound empty receipt before launchd
bootstrap. The guardian writes and fsyncs the exact stop marker only after a
complete coalition drain and native leader reap, before sending its final
frame. Recovery reads it under the existing producer fence. Missing, partial,
wrong-mode, linked and malformed receipts remain `UNKNOWN`; a failed write
cannot produce a successful final frame. No historical PID grants authority.

Focused source tests on Windows passed 32 cases with 16 platform skips. A
wheel built from this worktree includes `macos_recovery.py`; the same selected
tests ran against that wheel outside the source import path and passed 32
cases with 16 platform skips. These checks cover routing and portable contract
logic, not physical macOS containment. Core CI now runs four installed-wheel
owner-crash cuts in a supported Intel macOS GUI session: before claim,
claimed without a guardian, after native spawn and after birth persistence.
The claims and slots must remain fenced and counted until exact proof is read.

Core CI run `39332931455` passed its Intel macOS 3.13 job. The retained
installed-wheel report records `NEVER_CLAIMED` before claim,
`CONTAINER_UNCERTAIN` after claim without a guardian, and exact
`CONTAINER_STOPPED` proof after spawn and birth. The companion native
containment campaign passed all scenarios, including ten double-fork drains
and three owner-SIGKILL cuts, with no surviving children. Ubuntu 3.11–3.13
and Windows 3.11–3.12 also passed. Windows 3.13 passed its complete source
suite and offline wheel/sdist installation, but the hosted job's 30-minute
limit interrupted clean-wheel resource verification. The workflow now allows
45 minutes for this same matrix and unchanged checks. The original run does
not qualify the wheel because its SBOM job was skipped.

Nexus and Connector must vendor the resulting qualified Core wheel before any
joint installed acceptance. This checkpoint does not close M2's later
handshake, receipt and ACK crash cuts.
