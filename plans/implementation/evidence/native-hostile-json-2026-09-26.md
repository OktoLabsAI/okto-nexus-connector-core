# K10.3 native stdout hostile-JSON boundary — 2026-09-26

The Core-owned Codex, Pi and Claude-stream adapters now parse bounded native
stdout lines with the strict Core JSON parser. Duplicate object keys and
non-finite constants (`NaN`) are refused before dispatch. Codex also rejects
non-object JSON-RPC messages instead of silently ignoring them, and catches
deep-parser recursion without terminating its reader thread. Its malformed
diagnostic retains at most 2,000 characters from the hostile line. Pi and
Claude retain their adapter-specific error event categories. All three
continue draining the native stream and observe the subsequent real turn
terminal; no malformed line is interpreted as a terminal.

Codex and Pi also cap parse-error diagnostics at 2,000 characters, since a
duplicate key itself can be arbitrarily long within a bounded frame.

The scripted peer cases exercise actual subprocess stdout, not only a parser
unit. Codex sends duplicate-key, `NaN`, non-object and 20,000-level nested
JSON lines before a valid completion; Pi and Claude each send duplicate-key
and `NaN` lines before their valid settled/result message. The three focused
tests passed on Windows 11 and Ubuntu WSL2 under Python 3.11, 3.12 and 3.13
(18 outcomes). WSL2/Python 3.12 explicitly imports this project's `src` to
bypass a stale editable installation. No sibling Nexus code is imported.

This is partial TK-39 evidence, not provider-version fuzz qualification. The
native protocols may have other hostile shapes, and real provider output,
platforms beyond Windows/WSL2, sustained throughput and secret redaction
under all malformed lines remain to be qualified.

The final Windows/WSL2 Python 3.13 artifact pair matched byte-for-byte:
wheel SHA-256 `a5c1523b879d78c5ee38164012a6bd94ef9f5b8289f96e5580f3c8ce4469b96d`
and sdist SHA-256
`a86d04cda36b702259d959270996268989b66faa3852175cee3f005a2d90df8a`.
Strict Twine and development-mode release validation passed;
`publishable` remains false.
After the final diagnostic caps, full Python 3.13 suites passed on the stable
tree: Windows 450 passed/73 skipped and WSL2 509 passed/14 skipped. Each had
the expected injected legacy Pi thread warning. Windows offline wheel/sdist
installation and clean-wheel consumer smokes passed for the artifact pair.

## Unicode and streaming bounds follow-up

`strict_json` now validates parsed strings/keys for unpaired surrogate code
points and integers for the interoperable JSON range before returning them
to any consumer. Codex, Pi and Claude-stream subprocess peers inject both
forms before their real terminal, in addition to duplicate keys and `NaN`;
the terminals still arrive. Deep JSON in a selected host config is now
translated to typed `PROFILE_DRIFT` instead of escaping as `RecursionError`.
The Core JSONL decoder closes on deep parser failure, rejects invalid byte
limits, caps one input chunk at its frame-byte limit (at most 1 MiB), and
caps one returned batch at 1,024 records. Callers can split larger reads.

The 21 focused parser/config/adapter cases passed on Windows and WSL2 under
Python 3.11, 3.12 and 3.13 (126 outcomes). These tests use this Core source;
the real-provider, broader OS and statistical fuzz gates remain open.

The Unicode/streaming-bounds revision produced byte-identical Windows/WSL2
Python 3.13 artifacts: wheel SHA-256
`2ae84d202dd14cc53fcb9acbea8a1c3e0255ff7304a04e02417b48298739e3d5`,
sdist SHA-256
`caea683c135bcbb9f39ede620ac54fd9a1f42844fa13a85332b5aebfd4e94533`.
Strict Twine and development-mode release validation passed;
`publishable` remains false.

The stable Python 3.13 full suites passed: Windows 462 passed/73 skipped and
WSL2 521 passed/14 skipped, each with the expected injected legacy Pi thread
warning. Windows offline wheel/sdist installation and clean-wheel consumer
smokes passed for the final artifact pair.
