# Bounded NXL r3 frame codec — 2026-09-25

`frame_codec.decode_frame` now checks a hard 1 MiB byte limit before UTF-8
decoding or JSON parsing, rejects duplicate keys, non-finite numbers and
non-JCS values, requires the exact NXL revision, and validates the bundled
Draft 2020-12 frame schema. Additional checks require every event in a batch
to share its envelope identity and contiguous sequence; inventory IDs cannot
be duplicated or simultaneously added and removed; an `OUTCOME_UNKNOWN`
receipt cannot claim no possible effect or safe retry. `encode_frame` performs
the same checks, writes deterministic JCS bytes plus LF, and counts that LF
inside the wire limit.

The runtime dependency is pinned to `jsonschema==4.26.0`, matching the local
version and its documented Draft 2020-12 support. This is a local consumer
kit, not yet an NXL WebSocket transport or multi-consumer conformance result.
The pre-release r3 `operation.submit` bundle was refreshed on 2026-09-25 to
carry `expected_turn_id` for `turn.interrupt`/`turn.steer` and reject it for
other actions. The codec recomputes the full semantic intent hash (including
the expected turn, excluding reconnect generation) before an operation may be
admitted. The fixture generator emits independently computed JCS hashes for
submit/control frames; tests prove payload/configuration/turn changes with an
old hash fail, while a connection-generation change preserves validity. This
is a **breaking change to the unpublished development-partial r3 bundle**:
its manifest hashes changed and downstream consumers must pin/verify the new
bundle before use. No published compatibility claim is made for the earlier
partial r3 artifact.

Verification on Windows/Python 3.13:

- All positive/negative frame fixtures and new malformed/oversized/semantic
  cases passed in focused tests.
- Full `pytest -q`: 221 passed, 66 skipped.
- `python -m build --wheel --sdist` and `python tools/verify_wheel.py`:
  passed; clean wheel installation exercised codec encode/decode.
- Wheel SHA-256: `a4b1eae793910cc0293f8ba92544cd746161a1d826ceceb385fe0da5d63a34f2`.
- Sdist SHA-256: `f6e1fdcaffe55faa5e4d22394e732d4ddbfd4b9e6e79a0200e97c67257b55861`.

No external consumer or live network path was modified or qualified.

The later contract refresh passed focused schema/codec tests and full
`pytest -q` (`252 passed, 66 skipped`). `contracts/generate.py --check`, local
wheel/sdist build and clean-wheel verification passed. Refreshed wheel SHA-256:
`3244efc0826d94e29d4df10fbb083d089de2ca10fcc6484642f5184f0dfa707a`;
sdist SHA-256:
`18e636c7d1e3c4daa2ca56bb4a36d40510fb1991e1fddac12fbc475d01e4f543`.
The historical counts and hashes above refer to the earlier r3 artifact, not
this refreshed bundle.

K10 resource-bound update: `encode_frame` now validates its requested limit
before materialization and walks the materialized JSON container graph before
JCS allocation. The walk rejects cycles and uses a lower bound on encoded
bytes to reject definitely oversized host objects; the existing exact JCS
length/schema check remains authoritative, so this preflight cannot reject a
frame that would fit. Hostile-input tests cover an oversized in-memory
payload without invoking JCS, a cyclic payload, invalid limits, escaped
duplicate keys, unpaired surrogate, enormous exponent/integer, excessive
nesting and malformed UTF-8. This is bounded local codec evidence, not a
complete fuzz campaign of provider output or host configuration (TK-39).
An additional fixed-seed corpus mutates 600 frames across heartbeat, event
batch and operation submit; each mutation either raises a typed Core error or
round-trips through the same codec. The preflight traversal keeps auxiliary
stack size proportional to nesting depth, not list length.
