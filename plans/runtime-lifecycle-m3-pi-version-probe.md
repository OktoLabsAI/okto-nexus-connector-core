# M3 Pi version-probe deadline: real installed UI checkpoint

Date: 2026-10-17. Development branch `feature/v0.0.12`; no global rollout.

An installed Nexus 0.3.1/Core 0.0.12 disposable instance on port 8204 used
the real Pi 0.87.1 Node bundle through the Nexus Agents connection wizard.
The selected installation's first verification failed with
`Native version probe exceeded its deadline`; a retry passed unchanged. A
direct `node cli.js --version` took 2.593 seconds on the same host. The
connection test then failed with `CONFIG_ERROR` while opening: its Core journal
retained an `OUTCOME_UNKNOWN` open and a fenced/stopped launch container, with
no native session birth. This is consistent with the version observation in
Pi's pre-transport open path, but the UI exposes only the stable error code.

Pi now allows 10 seconds for that owned, read-only version observation. The
generic probe and the Claude/Codex budgets remain three seconds. Timeout still
fences the producer and contains the process; this change only prevents a
healthy slow Node bundle from being classified as a failed installation or
session open. It does not cache version evidence or relax the fingerprint and
ownership checks.

The three focused source tests passed, including a healthy 3.4-second probe
that failed against the previously installed Core. A rebuilt 0.0.12 wheel
(`004a9472140bf2b89c1820281ba7c4a9a658a924adc0fe1e4fcdec749059f8b5`)
was installed into the disposable environment. The same three installed
tests passed with isolated imports and `pip check` found no broken dependency.

The retained disposable Nexus was restarted normally with that installed
wheel. Through the same browser UI, the Pi connection test reached
`Connection verified`: a real model turn succeeded and the temporary session
closed. Saving the connection showed `Local · Online`. A Meta-harness message
then received a Pi response and 1/1 acknowledgement, with its input, actions
and result visible in the live terminal. A second message in the same session
also responded with 1/1 acknowledgement.

The first Meta-harness session still took about 162 seconds from message
submission to `Harness ready` (16:49:03 to 16:51:45 local UI time), then
completed its turn at 16:52:07. The second warm turn was much faster. That
cold-start cost is unresolved M3/M7 work; this checkpoint must not be cited as
complete startup-latency qualification. The Pi sent an explicit Nexus message
as well as its final runtime result, so two reply cards appeared. UI-A and the
three-provider/Connector gates remain open.

The fixture then drained normally and resumed with its saved connection. Its
agent admission fence cleared automatically about two seconds after
`RECOVERY_READY`; Agents showed Pi Online, and a new Meta-harness message
returned `M4_PI_RESTART_OK` with 1/1 acknowledgement. The final fixture run
drained with no resources or error codes; the test port and browser were
closed. The global Nexus generation was untouched.
