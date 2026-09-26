# K06 Pi ID-less terminal/start fence — 2026-09-26

Pi RPC's `agent_settled` has no native turn ID. The Core-owned copied-adapter
bridge now requires an `agent_start` observed while the current submitted
operation is active before it accepts `agent_settled` as that operation's
terminal. A terminal before that start raises `EVENT_OPERATION_MISMATCH`
with possible effect; the Core pump records its failure and leaves the
submitted receipt unsettled instead of claiming success. The bridge resets
this start evidence on each new submit, safe pre-write refusal and terminal.

Synthetic ordering tests cover both stale-terminal-before-start and normal
start-then-terminal paths. A contained Pi subprocess peer sends a prompt ACK
followed by an ID-less stale terminal before the new start; the public
runtime retains the operation at `SUBMITTED` and records a pump failure.
Focused bridge/Pi tests passed 30 cases in each local Windows/WSL2 × Python
3.11–3.13 environment. The wider Windows Pi/bridge/legacy suite passed
61 tests with one skip and the expected injected-thread warning.

Full Python 3.13 suites passed Windows 588/73 and, on a quiet rerun,
WSL2 647/14 (passed/skipped), each with the known injected-thread warning.
The first WSL2 full run had one unrelated Codex legacy handshake test miss
its 0.3-second timeout while builds and six offline installations ran in
parallel; that test passed isolated, then the entire WSL2 suite passed on a
quiet rerun. All six offline wheel/sdist installs passed. Normalized
Windows/WSL2 artifacts matched: wheel SHA-256
`0e2dd09c97a3b6d951c102505b5de2fdd6ea323c5bb8b86eb9c8c8c23531db08`,
sdist SHA-256
`151484212cbccea429caf1dc42cea81ce020e4402815ffb08960bf017d1e1ecd`.
Strict Twine and clean-wheel consumer checks passed; release validation
reports `publishable: false`.

This is a conservative fence, not full correlation: arbitrarily delayed
`agent_start`/`agent_settled` pairs without IDs can still be ambiguous.
Real Pi provider/version qualification and a version-bounded response/turn
correlation matrix remain open. No native Pi capability is enabled by this
test peer.
