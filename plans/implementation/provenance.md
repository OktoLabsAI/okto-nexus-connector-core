# Extraction inventory

Nexus source SHA: `7ed52c22865a92c3768bc32508ed9e35dc5efdc3`.
Original owner/copyright: Okto Labs, 2026. Original `LICENSE` copied unchanged
from that SHA. The terms are Elastic License 2.0 plus the SaaS/Branding
Addendum; no relicensing decision has been made.

| Core symbol/file | Nexus origin at source SHA | Change | Legacy regression |
|---|---|---|---|
| `native.framing` | `src/okto_nexus/adapters/outbound/harness/framing.py` | Byte-for-byte extraction; no application imports | Pending (`tests/test_runtime_fragmented_pipes.py`, `tests/test_runtime_io_boundaries.py`) |
| `native.event_buffers` | `src/okto_nexus/adapters/outbound/harness/event_buffers.py` | Byte-for-byte extraction; no application imports | `tests/test_runtime_event_buffers.py:103-115` assertion migrated to `tests/test_native_parity.py`; rest pending |
| `native.process.windows_process` | `src/okto_nexus/adapters/outbound/harness/windows_process.py` | Byte-for-byte extraction; no application imports | `tests/test_runtime_process_ownership.py:137-178` adapted to `tests/test_owned_process.py`; passed on Windows 11/Python 3.13 |
| `native.process.linux_process` | `src/okto_nexus/adapters/outbound/harness/linux_process.py` | Byte-for-byte extraction; no application imports | Linux backend not run on this Windows host; legacy Linux campaign pending |
| `native.process.linux_process_guardian` | `src/okto_nexus/adapters/outbound/harness/linux_process_guardian.py` | Byte-for-byte extraction; launched only by Linux backend | Linux backend not run on this Windows host |
| `native.native_inputs` | `src/okto_nexus/domain/native_inputs.py` | Byte-for-byte extraction of pure native input validation | Native input/approval regressions pending |
| `native.adapters.codex` | `src/okto_nexus/adapters/outbound/harness/codex.py` | Copied; application imports replaced by local neutral adapter types/process/environment. Legacy error renamed. | Preserved fake JSON-RPC peer; 32 adapted legacy tests passed on Windows, 1 provider test skipped. |
| `native.adapters.pi` | `src/okto_nexus/adapters/outbound/harness/pi.py` | Copied; same import neutralization. `turn_end` no longer claims completion before `agent_settled`. | Preserved fake Pi RPC peer; 27 adapted legacy tests passed on Windows, 1 provider test skipped. |
| `native.adapters.claude_code_stream` | `src/okto_nexus/adapters/outbound/harness/claude_code_stream.py` | Copied; application imports replaced by local neutral adapter types/process/environment. | Preserved fake stream-json peer; 29 adapted legacy tests passed on Windows, 7 provider/platform tests skipped. |
| `native.adapters.claude_code_attach` | `src/okto_nexus/adapters/outbound/harness/claude_code_attach.py` | Copied; application imports neutralized; ambient environment snapshot removed. | Unsupported-platform diagnostic passed on Windows; 57 adapted legacy tests skipped pending POSIX host. |
| `native.adapters.compatibility` | `src/okto_nexus/adapters/outbound/harness/compatibility.py` | Copied/changed to use owned three-pipe probe. Historical version allowlists retained separately; new wheel effective qualification defaults empty. | Synthetic Pi version probe passed; provider/SO qualification pending. |

Boundary recheck on 2026-09-26: `environment.py`/`owned_process.py` have
Core-owned neutral environment/process equivalents; native qualification and
redaction live in Core's compatibility/discovery and `native.redaction` code.
The copied adapters import only these local types. Nexus `envelope.py`
mixes canonical delivery envelopes/attempt ownership with native transport;
only neutral command correlation belongs in Core and is implemented in its
private runtime bridge. Nexus `event_journal.py` and `subscribers.py` use
application `HarnessEvent` and Server-owned projection/subscription semantics;
copying them would introduce a second backlog or canonical domain into Core.
Core instead owns its technical SQLite Journal port and bounded event sink.
No Core import or package dependency points at the sibling Nexus project.
The synchronous legacy adapter interface remains private; real provider,
host-adapter and POSIX parity remain open. The canonical `MessageService`,
grants, inbox, `AgentRepo` and whole supervisor are excluded.

The new models, protocol, journal and kernel are new Core code and are not
claimed as behavior-preserving extractions.
