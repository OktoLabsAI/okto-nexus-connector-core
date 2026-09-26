# K06.2 Pi fallback response-correlation fence — 2026-09-26

The Core-owned Pi RPC transport currently uses the observed legacy wire
shape: responses echo `command` but no request ID. It serializes commands,
yet serialization alone cannot distinguish a late response to a timed-out
command from a reply to a later command of the same verb. Once a command
times out, or an attempted write/flush fails ambiguously, this transport now
marks correlation lost. Any later command is refused before protocol write
with explicit `not_sent` evidence; the prior timeout/write retains uncertain
effect attribution. A request that merely times out waiting to acquire the
single-flight lock also reports `not_sent`, without poisoning the active
command. Intentional close/child death likewise fences pending state.

A scripted subprocess delayed the first `get_state` response past its
timeout. The second `get_state` was refused before write, the late response
was reported as unmatched, and the child log contained exactly one request.
A separate test injected an ambiguous write failure and verified no second
write occurred; a lock-contention refusal was marked not sent. Both focused
tests passed on Windows 11 and Ubuntu WSL2 under Python 3.11, 3.12 and 3.13
(12 outcomes). All code and fixtures are local to this Core project.

This is a fail-closed fallback, not proof that a newer Pi version lacks an
echoed ID or supports out-of-order correlation. Real binary/version capture,
qualified ID-aware concurrency, provider effects and host replay/reconcile
remain open for K06.2/TK-25.
An unsolicited duplicate response racing with a later same-verb request
cannot be disambiguated on this ID-less wire; the supported version must
either guarantee one response per command or expose a qualified echoed ID.

Windows/WSL2 Python 3.13 builds matched byte-for-byte: wheel SHA-256
`10b5b0385ea0dbface89a88d8c816a87720317797ae0c3b7c1417020de66e7a5`,
sdist SHA-256
`cf392f422a3336682063cd6467b4cc653fc877c733ca99125fe631bd2ea0012f`.
Strict Twine and development-mode release validation passed;
`publishable` remains false.
The stable full Python 3.13 suites passed: Windows 467 passed/73 skipped and
WSL2 526 passed/14 skipped, each with the expected injected legacy Pi thread
warning. Windows offline wheel/sdist installation and clean-wheel embedded
and remote consumer smokes passed for this artifact pair.
