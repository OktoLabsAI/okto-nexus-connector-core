# Durable opening generations — 2026-09-26

New `runtime.open` admissions pass `ExecutionContext.connection_generation`
and `session_owner_generation` into the Journal port. SQLite stores them in
`session_open_generations` in the **same transaction** as the immutable
session claim and operation receipt. `claimed_sessions` pages return the
original opening generations. Claims from older journals or direct test
admissions without those fields return `None`; no current owner is inferred.

Generation inputs must be a positive signed-64-bit integer pair, not booleans.
A duplicate open with a stored pair rejects a different or omitted pair as
`OPERATION_CONFLICT`; a new operation cannot claim the same session. The
existing intent hash also binds the full `ExecutionContext` in RuntimeCore.
Injected operation-insert failure rolls back both claim and generations.
Independent process contenders leave one matching claim/generation pair.
Reopen and abrupt journal/process-owner crash cuts preserve committed opening
generations while leaving any absent birth record absent.

The reusable Journal-port conformance and restart kits now require the
generation pair and detect a host adapter that silently drops it. Focused
tests passed on local Windows/WSL2 × Python 3.11–3.13 (92 selected cases per
environment); full Python 3.13 suites passed Windows 554/73 and WSL2 613/14
(passed/skipped), each with the expected injected legacy Pi warning.

Normalized Windows/WSL2 builds matched byte-for-byte: wheel SHA-256
`6255144a8d481b627cd710c1824f9669d3a16ec9c3df721eb4cc832151b25977`,
sdist SHA-256
`c062ff4462bead47914ef11c619f47d703f52625bda27dd7250e8f53ace56447`.
Strict Twine and development-mode release validation passed with
`publishable:false`. The installed wheel passed clean import and embedded/
remote synthetic consumer checks. Wheel and sdist passed offline installation
and resource checks in all six local Windows/WSL2 × Python 3.11–3.13
combinations for this exact pair.

These fields identify the generations that authorized the **opening**, not
the currently connected channel or current physical owner. They do not grant
takeover, reattach, PID control, or lease renewal after restart. Durable CAS
for later connection generations, cross-instance arbitration and real host
adapter parity remain open under J23/K04.
