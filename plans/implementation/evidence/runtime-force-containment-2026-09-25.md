# K04 independent owned-tree force request — 2026-09-25

The three managed copied connectors (Codex app-server, Pi RPC and Claude
stream) expose a Core-owned `force_stop()` that calls `kill()` on their
selected owned-process backend. The async bridge fences further sends before
invoking it in a worker thread. The runtime schedules this containment at the
end of the drain+interrupt windows, independently of a native send or close
that may still be awaiting a response. The public shutdown method dispatches
any due request before returning; it never force-stops `claude_attach`.
Before calling the backend, the Core admits a deterministic, critical
`runtime.shutdown_force` operation as `SUBMISSION_STARTED`. A returned request
becomes `SUBMITTED`, not proof of stop. Under journal saturation, containment
is still attempted and the session is faulted; no durable force receipt can
then be claimed.

Force is a request, not release evidence. An in-flight native operation keeps
its session slot reserved, even if process observation says `STOPPED`. Once
the native call settles, normal close/observe can release ownership. If a
force request was made, a later generic `graceful` close result is reduced to
`unknown` rather than attributing the stop to the wrong mechanism. A backend
can report `forced` only with its own evidence. Failed or stuck force calls
leave an `unknown` outcome.

Synthetic runtime tests hold a native send across the force deadline and
verify force dispatch, `unknown` report, retained ownership and late cleanup.
The held-send test also reads the journal at the instant of force and sees
`SUBMISSION_STARTED` before the process action.
Local Codex/Pi/Claude fixture peers each prove an observed owned-tree stop
through the bridge on Windows and WSL2. Explicit backend force tests now
hold OS process handles (Windows) or pidfds (Linux) for the leader and a
descendant. The Windows Job Object kills both; the Linux guardian also reaps
an escaped-session descendant. These are not real provider runs;
Windows/Ubuntu CI and macOS/freeBSD shutdown campaigns have not run. A host
must not present this as a fully qualified TK-20 result.
