# In-process generation CAS fence — 2026-09-26

`LocalRuntimeCore.renew_lease` and `revoke_lease` previously updated the
session context under the runtime state lock while an already-admitted normal
or control send could be awaiting its native adapter. The update could return
success before that old-channel send reached the adapter.

Both lease updates now acquire the session's normal and control command locks
before validating and mutating the context. They recheck identity/generation
inside the locks. The wait is bounded by `reconnect_fence_seconds` (default
5 seconds, finite positive configuration). A timed-out renewal raises
`RECONNECT_BUSY`; a timed-out revocation raises `REVOKE_BUSY`. Both leave the
lease update unapplied and set `retry_safe=True` for retrying that update;
they do not characterize the pending native intent as safe to replay.

Synthetic native sends held across each boundary verified that the update
cannot return success while the old normal/control effect is pending, and
that retry after the send completes succeeds. Old contexts fail after CAS or
revocation. Focused tests passed on local Windows/WSL2 × Python
3.11–3.13; Python 3.13 runtime/docs suites passed 53 on each OS. Full Python
3.13 suites passed Windows 547/73 and WSL2 606/14 (passed/skipped), each
with the expected legacy Pi injected-failure warning.

Normalized Windows/WSL2 artifacts matched byte-for-byte: wheel SHA-256
`7cb799d6bd6336ec4de984c9c23f62757c0752c24899c91a9d0b813a1d657e21`,
sdist SHA-256
`a16f63b722f9d69d3d7bec6bc4a577328d2748674f262f9af836d8812009cf56`.
Strict Twine and development-mode release validation passed with
`publishable:false`. The installed wheel passed clean import/embedded/remote
synthetic consumer checks. Wheel and sdist passed offline installation and
resource checks in all six local Windows/WSL2 × Python 3.11–3.13
combinations for this exact pair.

This only fences sends inside one live `LocalRuntimeCore` binding. It does
not undo a command already accepted by a provider, transfer physical process
ownership after restart, persist connection generations, resolve two active
Core instances, or establish Server/Connector adapter parity. A busy lease
update needs host reconciliation before retry or shutdown; it is not evidence
that an old operation was not sent.
