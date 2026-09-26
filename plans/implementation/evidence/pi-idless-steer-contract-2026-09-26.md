# Pi ID-less public steer/follow-up contract — 2026-09-26

Closes the public-contract part of the K06.3 gap recorded in the Pi 0.87.1
milestone ("public ID-less Pi steer/follow-up targeting"). Pi's RPC wire
carries no native turn ID, so the previous runtime admitted `turn.steer`
only for Codex with an explicit `expected_turn_id`. The contract is now:

- `turn.steer` admission is per adapter, before operation admission:
  Codex app-server still requires `expected_turn_id` naming the active
  native turn (unchanged); `pi_rpc` is steered only ID-less and refuses a
  supplied native turn ID with `CAPABILITY_UNSUPPORTED`; every other
  adapter still refuses steer outright.
- The ID-less Pi target is the agent run Core observed starting
  (`agent_start`) for the active submit. With no active submit or no
  observed start, the copied-adapter bridge refuses before the native
  write with a retry-safe `STALE_TURN` (`RuntimeCommandNotSent`), which
  the kernel journals as a durable safe failure, never a guess.
- Delivery follows Pi's native next-turn-boundary steering queue: the
  steered content stays part of the same active turn, `queue_update` is
  the observable queue event, and only that turn's `agent_settled`
  settles the submit receipt. A follow-up after `agent_settled` is a new
  `turn.submit`.
- Every steer still requires `turn.steer` in the host-issued
  `ExecutionContext` and in the active binding.

Implementation: `runtime.py` (`control`/`_send` per-adapter gate),
`native/runtime_bridge.py` (`CopiedAdapterSession.send` pre-write Pi steer
gate), `docs/api.md` and `docs/adapters.md` contract text.

New tests: `test_pi_steer_is_admitted_without_native_turn_id`
(public runtime admission/refusal), `test_pi_steer_targets_only_the_
observed_active_agent_run` (bridge pre-write refusals and admission),
`test_pi_public_idless_steer_settles_active_turn` and
`test_pi_public_interrupt_settles_and_allows_follow_up_submit` (contained
`pi_rpc_peer.py` subprocess through the public runtime and journal: held
turn steered at the queue boundary, `queue_update` payload, terminal
correlation to the submit, submit receipt `SUCCEEDED`/`FAILED`, steer
receipt honestly `SUBMITTED`, follow-up submit after a cancelled turn).
Synthetic consumer integration: `tools/consumer_smoke.py`'s embedded path
now exercises the ID-less steer admission and the native-turn-ID refusal
shape against the installed wheel.

No real model turn, provider control or provider campaign was run; the
milestone's single authorized turn was not reused or repeated. Extension
UI host-decision surfacing, real-provider retry/compaction/cancel/shutdown
qualification, Linux provider behavior and real host consumers remain
open; TK-24/TK-25/TK-26 stay `NOT_RUN`.

Verification (all local, `rtk`-prefixed):

- Focused steer suites
  `pytest tests/test_native_runtime_bridge.py tests/test_runtime.py -q -k "pi_steer or pi_public or steer"`:
  6 passed in each local Windows/WSL2 × Python 3.11/3.12/3.13 environment
  (Windows 3.11/3.12 used fresh venvs; WSL2 reused the recorded 3.11/3.12
  environments).
- Full Python 3.13 suites: Windows `pytest tests/ -q` 602 passed/73
  skipped; WSL2 `PYTHONPATH=src` 661 passed/14 skipped; both with only the
  known injected legacy Pi thread warning. (+4 tests over the milestone
  counts.)
- Normalized `tools/build_artifacts.py` builds are byte-identical across
  Windows and WSL2: wheel SHA-256
  `b599275c75f76162760e781f3a7af4534afc3f4c2133966cdc531ca2be6ccdcb`,
  sdist SHA-256
  `fe7b15736c93f1e3d4db6cd96152ef3ebcba00414ea841ac663ff983d2e6c581`
  (final pair after the bundled guide updates; the intermediate
  pre-documentation sdist was
  `42aaa0b1bb45b018a227cf348df5b0203ff371ce46ccb689b00093254144c865`,
  with the same wheel).
- Strict Twine check passed for both artifacts.
  `tools/validate_release.py --allow-development` reports
  `publishable:false`.
- `tools/verify_offline_artifacts.py` (offline wheel and sdist install,
  bundled resources, both consumer smoke roles) passed on Windows/Python
  3.13 (`build/offline-wheelhouse`) and WSL2/Python 3.13
  (`/var/tmp/nexus-core-linux313-wheelhouse-20260926`). The 3.11/3.12
  offline installs were not rerun for this pair; those environments ran
  the focused suites only.
