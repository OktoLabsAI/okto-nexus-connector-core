# Selected Windows Pi Node/CLI launch — 2026-09-26

The supplied Pi `bin/pi` is a `sh` launcher and is not executed as a Windows
native candidate. Core now has a local explicit-selection function,
`candidate_pi_node_cli`, for the trusted Node executable plus the installed
`@earendil-works/pi-coding-agent/dist/bundle/cli.js` entry point. It rejects
other script layouts and untrusted selections. The candidate fingerprint is
domain-separated and combines both resolved paths and both SHA-256 file
hashes, so qualifying Node alone cannot authorize arbitrary JavaScript.

`probe_selected_pi` runs the sealed version observation as
`node cli.js --version`; `prepare_launch` realizes `node cli.js --mode rpc`
and `verify_prepared` rechecks both files before open. This is implemented
inside Core and does not reference the sibling Nexus source checkout. The
native build qualification allowlist remains empty.

With the user-supplied installed paths on Windows, the no-turn selection,
version observation, preparation and drift check returned version `0.87.1`,
architecture `x86_64`, four argv elements and a bound CLI path. No model
request was made. Synthetic tests cover script and Node identity/argv,
untrusted/arbitrary script rejection and post-selection script drift.
The focused profile/probe suite passed Windows 14 and WSL2 13/1
(passed/skipped) on each Python 3.11–3.13 environment.

The complete Python 3.13 suites passed Windows 593/73 and WSL2 652/14
(passed/skipped), each with the known legacy injected-thread warning. An
initial WSL2 run had six child-process import failures because the test
invocation supplied a relative `PYTHONPATH=src` while the children changed
directory; repeating with the absolute source path passed. The normalized
Windows/WSL2 wheel and sdist matched byte-for-byte: SHA-256
`08954a43ed2119e611ba42130fe7b5119e0539a167f09e739b46ea88a48362de`
and `e755c86123ae232919b450ba05daffec740be08303a5a513d8adf5a115cdaca0`
respectively. Strict Twine, development release validation, clean-wheel
consumers and offline wheel/sdist installs in all six local OS/Python
environments passed. The development artifacts are not publishable.

This establishes only selected launch preparation. Real managed open through
the Core factory, controls, extension UI, failure paths, Linux provider
behavior and production allowlisting remain unqualified.
