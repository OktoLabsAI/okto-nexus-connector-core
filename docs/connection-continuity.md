# R4 connection continuity

Continuity is negotiated through `hello`/`welcome.control_capabilities`. Hosts
must not send extension frames unless the peer advertised support.

- `connection_renewal_v1`: the executor sends a scoped `connection.renew` with a
  unique request ID. The server replies with `connection.renewed`, the same
  request ID, `expires_in` (1–600 seconds), and the renewed `binding_ids`.
  Renewal preserves ticket material, lane attempts, connection generation, and
  native session ownership. It does not renew an execution lease or revive an
  expired/revoked credential. The executor anchors deadlines before sending.
- `heartbeat_ack_v1`: the server echoes a valid heartbeat after checking the
  connection owner. The executor detects missing inbound traffic with a
  monotonic deadline. The server independently bounds inbound silence.
- `connection_resume_v1`: a hello may include `resume_connection_id` and
  `resume_connection_generation`. The server confirms with `welcome.resumed`.
  This is a bounded recovery of the same authenticated owner, not a new claim
  on a native process. An implementation must reject stale generations, a new
  bootstrap credential, expired authority, and superseding owners.

The Connector attempts fast resume only when no control request is awaiting a
reply. Uncertain requests retain the existing durable reconciliation path;
native effects must never be blindly replayed. Existing execution lease
deadlines remain in force during transport recovery.
