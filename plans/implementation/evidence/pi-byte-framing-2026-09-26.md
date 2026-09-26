# K06.1 Pi byte/LF framing — 2026-09-26

The Core-owned Pi adapter now reads its subprocess stdout from the binary
pipe, frames at LF with a hard 1 MiB byte ceiling, then strictly decodes each
complete frame as UTF-8. CRLF is accepted, while U+2028/U+2029 remain inside
the JSON record. A missing final LF and a frame exceeding the byte ceiling
close the transport with an explicit diagnostic; a complete line containing
invalid UTF-8 is diagnosed and skipped without losing subsequent records.
Stderr remains a separate bounded text tail, not protocol input. Native
JSON syntax/Unicode validation then uses the Core-owned strict parser.

A scripted Pi subprocess split a multibyte UTF-8 character across two pipe
writes, emitted CRLF and literal Unicode separators, then an invalid-byte
line before its real `agent_settled` terminal. The adapter preserved the
Unicode payload, emitted one malformed-line error for the invalid byte and
observed the terminal. Unit tests cover incomplete LF and over-limit frames.
Five focused cases passed on Windows/WSL2 × Python 3.11–3.13; the complete
Pi/native-framing subset passed on Windows and WSL2 Python 3.13 at 34 passed,
one explicitly skipped real-provider test and the expected injected legacy
Pi warning. The peer, helper and adapter all live in this Core project.

This closes the local framing mechanism gap, not full TK-24/K06: a real Pi
binary/provider version, backpressure under sustained native output, request
correlation and host integration remain unqualified.

Windows/WSL2 Python 3.13 builds matched byte-for-byte: wheel SHA-256
`6a0aa4caff004f9d7eda36fb3a4e4f366953f2454bdd38e03b496a5845b69c95`,
sdist SHA-256
`def2ae4bd8a1716fa0447cd2d7c2612e3164bb52fa60a29fc9946433f321a8ad`.
Strict Twine and development-mode release validation passed;
`publishable` remains false.
The stable full Python 3.13 suites passed: Windows 465 passed/73 skipped and
WSL2 524 passed/14 skipped, each with the expected injected legacy Pi thread
warning. Windows offline wheel/sdist installation and clean-wheel embedded
and remote consumer smokes passed for this artifact pair.
