# M3o — Pi native-action renewal during opening

Date: 2026-10-17. Branch: `feature/v0.0.12`. No global rollout.

In a disposable installed Nexus UI run, the first real Pi `runtime.open`
failed after 73 seconds with `BINDING_NOT_AUTHORIZED` before a process birth.
The session lease renewed during that opening. The receipt exposes only the
stable code, so it does not prove the precise Core frontier that refused it.

Code review identified a concrete mismatch: general opening authority
permits a new lease ID, serial and deadline for the same authorized subject,
while `PiNativeActionOwner._authorize` normalized only serial and deadline.
The Pi launch therefore rejected an otherwise valid lease rotation at its
pre-spawn native-action check. A focused test rotating the ID during listener
startup failed against the old implementation at `native_action_launch`.

The owner now accepts a new lease ID only when the serial advances, while
continuing to compare the agent, workspace, grant, boot, connection and other
context fields. Same-serial ID substitution, authorization drift, scope drift,
grant drift, boot drift, serial rollback and deadline rollback remain refused.
This is a safe pre-spawn correction; it does not replay a native write.

Validation: eight focused source cases passed, including the red case; one
adjacent socket timeout case first failed under host load with
`EXECUTOR_OFFLINE` and passed on rerun with the eight focused cases. The
installed wheel imported from site-packages and passed the same eight cases
plus one Pi native bridge case. Wheel SHA-256:
`95a6238deae20d1a98ea8c8a44dcb808c24e037eb01e0d38163265fc1dc72193`.
Nexus and Connector vendor this same artifact. Real UI requalification of
this exact wheel and cold-start phase/cost analysis remain open; the global
Nexus installation was not changed.
