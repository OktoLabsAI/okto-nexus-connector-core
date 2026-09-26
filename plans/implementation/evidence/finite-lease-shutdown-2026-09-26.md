# Finite lease and shutdown arithmetic — 2026-09-26

The runtime now rejects malformed host-issued monotonic lease deadlines
(`NaN`, infinity, booleans, strings, missing values and integers too large
to convert to a finite float) before `prepare`, `open` or a native `submit`.
`renew_lease` validates its incoming deadline before updating in-memory
authority. An `open` also rejects a finite deadline whose addition to the
configured grace period would overflow, preventing the lease watcher from
waiting on an infinite grace boundary.

Constructor lease timing and shutdown drain/interrupt budgets must remain
finite after addition. Invalid shutdown budgets fail before the runtime
is marked as draining. Tests assert there is no native factory call, no
admitted receipt and no native send for malformed lease contexts.

The runtime/docs focused suite passed 60 tests in each local Windows/WSL2 ×
Python 3.11–3.13 environment. Full Python 3.13 suites passed Windows
572/73 and WSL2 631/14 (passed/skipped), with the expected injected legacy
Pi warning. Normalized Windows/WSL2 builds produced identical artifacts:

- wheel SHA-256: `81708c2c8fd531fd5db7c23f3fa4a2222d41ec5d06ce1ed624adca99d9a3f702`
- sdist SHA-256: `1e95afd6e0bc498d7687dfec992cd8a72012fd2bd21f19a6df2229d8d8ae023c`

The pair passed strict Twine, clean-wheel import and embedded/remote consumer
smokes, and offline wheel/sdist installation on Windows and WSL2 with Python
3.11–3.13. Development release validation returned `publishable: false`.

This does not prove cross-host clock quality, durable generation takeover,
or physical cleanup after a crash.
