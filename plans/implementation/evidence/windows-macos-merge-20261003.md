# Windows regression after the macOS merge

The `feature/macos` tip `14f5ec9` was merged into the active integration branch
`feature/v0.2.0`, preserving `09e1dea` harness configuration and native
interactions. Core version: **0.2.57.dev0**. Host: Windows x86_64, Python 3.13.1.

## Core suite

Full suite: **1,247 passed, 100 skipped, 2 warnings** (431.53 seconds).
The Darwin-only smoke paths remain skipped on Windows. Portable Darwin checks
run against fakes, including argument validation, coalition census and stop
proof logic; no launchd execution is claimed here.

The first run found six portability errors in the new macOS tests. The tests
now simulate the Darwin platform only at the tested module boundary, refuse
any attempt to launch, and supply missing signal symbols only for mocked kill
calls. Production platform refusal remains intact. Existing Codex native-input
and Claude qualification assertions were reconciled with the previously
implemented exact-build contracts. Missing public API documentation was added.

## Real harness campaign

Nine scenarios passed against an isolated Nexus server loading the merged Core:

| Harness | Version | Model | Real reply | Native file write/read |
| --- | --- | --- | --- | --- |
| Codex | 0.159.0-alpha.12.1 | gpt-6.1-sol, low | PASS | PASS |
| Claude | 2.1.288 | sonnet, low | PASS | PASS |
| Pi | 0.87.1 | zai/glm-5.3, low | PASS | PASS |

Direct Nexus messages and runtime replies passed for Codex to Claude, Claude to
Pi, and Pi to Codex. Canonical message records identify the harness agent as
sender; response records identify the receiving harness, and the reply message
targets the original sender. The UI showed all three requests as READ. Twelve
runtime outputs were published. Final owner failure was null; shutdown returned
DRAINED with no resources or error codes.

## Limits and follow-up

An initial concurrent cold-open campaign failed with `PROFILE_DRIFT` at the
environment boundary: Claude created a file in the shared workspace while
other sessions were opening. The launch content guard seals directory size and
mtime, so ordinary directory changes can invalidate another launch. The entire
`native/runtime_bridge.py` file is unchanged from pre-merge `09e1dea`. The
successful campaign opens sessions before writing; it does not qualify the
concurrent cold-open/write scenario. This existing limitation needs a separate
directory-identity and dispatcher-containment review.

This campaign does not qualify every Nexus event, approvals, handoffs, native
questions, or any new Mac provider execution. Upstream Intel GUI-session
synthetic evidence is retained in `macos-native-acceptance-20261002.md`; its
headless, worker shutdown and other documented limitations still apply.
The operator's main server on port 8202 was not replaced by this isolated test.

Nexus integration regression: **22 passed** (inventory, harness settings,
managed messages, native messages and question recipients). Nexus and Connector
pins and vendored artifacts now target Core 0.2.57.dev0; source bytes, wheel
copies and manifest hashes were verified.

Connector full suite, with both wheels installed in a fresh Python 3.13 venv:
**734 passed, 1 skipped** (732.95 seconds). Its first source-only run exposed
isolated CLI subprocesses unable to import user-site packages, a missing new
vendored Core wheel, and a Pi fixture selecting the first host installation
rather than its own candidate reference. The installed rerun includes CLI,
packaging, Windows Job Object, IPC, native-action and regression tests.
