# Pi compound version probe and rejected prompt — 2026-09-26

The Pi connector's default version-command construction previously kept
only the first argv element. After selecting a Windows Node + CLI pair,
this ran `node --version` rather than the selected Pi package. The connector
now derives `node cli.js --version` for that command shape. The no-turn
adapter probe against the installed 0.87.1 package, without an explicit
version-command override, observed Pi `0.87.1`, selected ID-echo response
correlation and completed readiness without a model request.

The installed RPC reference says `prompt` success acknowledges command
acceptance only; a failed response rejects the prompt before acceptance.
The copied adapter had emitted an error event but returned normally, letting
Core record `SUBMITTED` for a rejected prompt with no terminal event. It
now also raises a native error when `prompt` is rejected or malformed. The
same conservative rejection rule covers `steer` and `abort`; a synthetic Pi
peer exercises both, and a public runtime/journal test covers a rejected
`abort`. Public Pi steer is still gated pending a turn-target contract.
Because the protocol write already occurred, it does **not** set the
pre-write `not_sent` marker. The Core kernel therefore retains
`OUTCOME_UNKNOWN` with `possible_effect=true`, never a false submitted or
successful receipt. A contained Pi peer exercises the error event and the
public runtime/journal receipts. This conservative result does not prove the
provider was never invoked or grant automatic replay.

No additional real model turn or provider control was used. Exact-build
production qualification remains disabled.

The focused Pi/bridge/legacy suite passed 68 tests with one platform skip
in each local Windows/WSL2 × Python 3.11–3.13 environment. Full Python 3.13
suites passed Windows 598/73 and WSL2 657/14 (passed/skipped), each with the
known injected-thread warning. Normalized Windows and WSL2 artifacts are
byte-identical: wheel SHA-256
`eab0aef249e070b8070f2155e6ba960a4078b68f0993ab3dfd6e5032537f224f`,
sdist SHA-256
`63109b17ff730642465a526fce256fd9d3c41bb994e721f070a73528921c6f57`.
Development release validation, strict Twine, clean-wheel consumers and
offline wheel/sdist installs on all six local OS/Python combinations passed.
The `0.1.0.dev0` artifacts remain non-publishable.
