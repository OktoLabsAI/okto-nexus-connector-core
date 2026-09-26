# Installed Pi 0.87.1 RPC observation — 2026-09-26

The user supplied a Windows managed installation at
`C:\Users\jpamb\.pi\agent\install\releases\0.87.1\`. Its `bin\pi` is a
105-byte `sh` launcher, not a Windows executable accepted by Core's selected
binary gate. Its launcher JavaScript resolves the current release and starts
the package CLI with Node. We used explicit `C:\Program Files\nodejs\node.exe`
and the release's `@earendil-works/pi-coding-agent/dist/bundle/cli.js` for
read-only probing; no runtime dependency on the sibling Nexus checkout was
introduced.

The local installed package reports version 0.87.1. Its bundled `docs/rpc.md`
says command IDs are optional but echoed by responses, and asynchronous
commands should correlate by ID. `tools/probe_pi_rpc.py` sent only
`{"id":"core-probe-1","type":"get_state"}` with disposable config,
`--no-session`, no tools/extensions/skills/templates/themes/context files,
and offline mode. It observed one successful `get_state` response, a data
object, an exact ID echo and clean exit. No model prompt was sent.
`tools/probe_pi_adapter.py` then started and closed the copied Core adapter
under disposable config/session directories using the same explicit Node/CLI
pair. Its readiness probe succeeded and selected the 0.87.1 ID-correlation
path without a model request.

Observed SHA-256: Node executable
`3331e1ffe19874215472217c5e94f5a0c6d8e18c4ac7111d3937aa0ad5e9b4a5`;
Pi CLI JavaScript
`e79626f2dd6f94aa45d30f3fa63cd84319a6eefcd150b353cfaf274366926774`.
These identify this local observation; they are not a production allowlist.

The copied Pi transport now requires echoed IDs for exact observed version
0.87.1. It bounds concurrent requests to 32, matches both ID and verb, and
does not let a late timed-out reply satisfy a newer same-verb command. The
older 0.85.1 ID-less path keeps its serialized fallback and uncertainty
fence. A synthetic peer exercises out-of-order same-verb replies and a late
response. Concurrency under provider load, extension UI behavior and
production compound Node/CLI selection remain unqualified. The effective
native qualification allowlist remains empty; this observation does not
enable Pi for a production host.

After explicit user authorization for one provider call, `tools/probe_pi_turn.py`
used the existing Pi configuration for authentication and a disposable
session directory, with built-in tools, extensions, skills, templates,
themes and context files disabled. It disabled automatic retries before
sending one prompt. The real 0.87.1 adapter observed prompt acceptance,
`agent_start`, `turn_start`, assistant message deltas, `turn_end`, `agent_end`
and `agent_settled`, with assistant `stopReason: stop`. It logged only event
types/outcome, not response text or credentials. This supports the Windows
single-turn conversation path and terminal ordering for this installed
release. It does not establish interrupt/steer/follow-up, failure handling,
multiple sessions, real extension UI, Linux behavior or host consumption.

After the ID-correlation change, focused Pi/bridge tests passed 32 cases in
each local Windows/WSL2 × Python 3.11–3.13 environment. Full Python 3.13
suites passed Windows 590/73 and WSL2 649/14 (passed/skipped), each with the
known legacy injected-thread warning.

The current normalized Windows and WSL2 build outputs are byte-identical:
wheel SHA-256 `8c772929ba6f8cfcfb5367f851b80b1a896e962f5c6931fff9160fba31e111a8`;
sdist SHA-256 `e72937bdee80c09b47cf997ee67972811c987ebd6c699056f4d85c53c93f7946`.
Development release validation, strict Twine and clean-wheel consumer checks
passed. The same wheel and sdist passed offline installation/resource checks
in all six local Windows/WSL2 × Python 3.11–3.13 combinations. Version
`0.1.0.dev0` remains explicitly non-publishable.
