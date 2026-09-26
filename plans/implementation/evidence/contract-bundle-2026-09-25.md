# NXL development contract bundle — 2026-09-25

Revision: `nxl-1-agent-centric-http-only-2026-09-25-r3`.

The Core-owned `contracts/generate.py` deterministically emits seven JSON
Schema 2020-12 files (frame, intent, event, error, inventory, capability and
HTTP response), positive/negative fixtures, and a manifest with SHA-256 for
each generated resource. The frame schema contains exactly the 20 frame
families in A.8 of the plan. There are 20 positive and 25 negative frame
fixtures; each non-frame schema has a positive and a negative fixture.

Validation performed:

- `python contracts/generate.py --check`: generated files match the source.
- `pytest -q tests/test_bundle.py tests/test_protocol.py`: nine passed.
- `pytest -q`: 160 passed, 66 skipped.
- `python -m build --wheel --sdist`: both artifacts built.
- `python tools/verify_wheel.py`: clean offline wheel installation/import,
  resource hashes, no Nexus/Connector imports in packaged Python, and sdist
  inclusion of generator and all seven schemas.

Artifact SHA-256: wheel
`6ff2a17eb3965b958952d1f9e056e0030d57fa52fc5d4388a456f4f1ca87f9ee`;
sdist `a00435734ba43227fe94ba59f0e6270a7a2d0917022c014788d89ca977240bcb`.

The manifest remains `development-partial`. This evidence does not establish
consumer conformance, complete RFC 8785 canonicalization (notably floats),
wire byte limits, all cross-field semantic constraints, or qualification of
actual providers and platforms. TK-05 and TK-07 therefore remain NOT_RUN as
full acceptance scenarios.
