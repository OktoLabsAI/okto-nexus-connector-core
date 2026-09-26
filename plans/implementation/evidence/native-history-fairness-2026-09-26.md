# K04/K10 transient native-history fairness — 2026-09-26

The Core-owned transient `NativeEventHistory` now supports per-session item
and serialized-byte quotas alongside its global limits. An ordered global
index and per-session indexes make eviction of the oldest event from either
scope constant-time; an evicted session is explicitly marked replay-expired.
The Codex shared-process adapter uses 512 events/1 MiB per session within
its existing 2,048-event/4 MiB global history. Pi, Claude stream and attach
retain their previous effective per-session ceilings by default. Invalid
quota configurations fail before an event is appended.

Synthetic two-session tests demonstrate that a noisy session exhausting its
item or byte budget evicts its own oldest events while a quiet session's
session-scoped transient replay remains available. The noisy session receives an explicit
replay-expired error, never a silently incomplete snapshot. Seven targeted
tests passed on Windows/WSL2 × Python 3.11–3.13 (42 outcomes). The combined
Codex/native-history subset passed at 47 tests/one expected real-provider
skip on Windows and WSL2 Python 3.13.

This protects a quiet session against one noisy session within the tested
global headroom. It is not a complete TK-40 fairness gate: global pressure
from many sessions, a slow subscribed consumer, native-process ownership,
urgent controls and real provider streaming still require campaign evidence.
Global unscoped replay intentionally reports expiration if any session
expired; hosts requiring continuity must use session-scoped durable replay.
The durable journal, not this bounded transient history, remains the source
of replay truth.

Windows/WSL2 Python 3.13 builds matched byte-for-byte: wheel SHA-256
`ccec3e29b299069d3744ae46995c903097a185aa42f48455bcdaf9340db14b78`,
sdist SHA-256
`9a88d7a90c9873603acb6ebbd45dcdbe5496073c24e7c96036e85f9c250cdb25`.
Strict Twine and development-mode release validation passed;
`publishable` remains false.
The stable full Python 3.13 suites passed: Windows 474 passed/73 skipped and
WSL2 533 passed/14 skipped, each with the expected injected legacy Pi thread
warning. Windows offline wheel/sdist installation and clean-wheel embedded
and remote consumer smokes passed for this artifact pair.
