# M2f — Linux planned-launch crash boundaries

2026-10-19. This is a focused M2 platform checkpoint, not full M2 acceptance.

The existing disposable owner fixture was exercised on Ubuntu/WSL2 with Python
3.11.15 at four launch boundaries. The test imports Core 0.0.12 from an
isolated installed wheel under `site-packages`, outside the source directory.
All four cases passed; the same four also passed against the editable source
package. Five selected Windows cases passed after the former module-level
Windows skip was moved to the Windows-only cases.

| Owner crash boundary | Recovered state | Required evidence |
| --- | --- | --- |
| Durable intent, before claim | `STOPPED` | `NEVER_CLAIMED` under the producer fence |
| Claimed, before guardian creation | `CONTAINER_UNCERTAIN` | No receipt exists; slot remains reserved |
| After guardian spawn, before birth record | `STOPPED` | Guardian's durable `CONTAINER_STOPPED` receipt |
| After birth record | `STOPPED` | The same exact guardian receipt |

All cases retain the original reservation until the host settles it; a fenced
old producer cannot launch again. The claim-only uncertainty is intentional:
absence of a Linux receipt is not proof that a child never existed. These tests
cover the existing no-replay/containment rule, not handshake, publication,
receipt or ACK crash cuts. macOS physical qualification and the broader M2
acceptance remain open. No product code or global installation changed.
