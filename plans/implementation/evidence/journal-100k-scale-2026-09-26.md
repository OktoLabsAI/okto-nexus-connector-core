# K04/K10 synthetic 100k-operation journal probe — 2026-09-26

`tools/profile_journal_admission.py` is a Core-owned, reusable local probe.
It creates temporary SQLite storage, admits 99,000 normal operations over
three Server/executor namespaces and 30 sessions, verifies normal refusal at
the global reserve, admits the remaining 1,000 critical operations, verifies
the hard row cap and duplicate lookup at saturation, then reopens the journal
and checks the durable counter/duplicate again. It uses no Nexus application
imports, provider, credentials or remote hosts.

| Environment | Command | Normal 99k | Full 100k | Reopen | DB/WAL/SHM bytes |
| --- | --- | ---: | ---: | ---: | --- |
| Windows 11, Python 3.13.1 | `rtk python tools/profile_journal_admission.py` | 79.749 s | 80.304 s | 0.348 s | 12,668,928 / 1,091,832 / 32,768 |
| Ubuntu WSL2, Python 3.13.14 | `rtk proxy wsl -d Ubuntu -- bash -lc 'cd /mnt/d/projetos/Techridy/okto-nexus-connector-core && /var/tmp/nexus-core-linux313-20260926/bin/python tools/profile_journal_admission.py'` | 59.929 s | 60.527 s | 0.131 s | 12,668,928 / 1,091,832 / 32,768 |

Both commands exited zero and reported the package source as this Core
worktree's `src/nexus_connector_core/journal.py`. The 10,000-operation batch
durations stayed between 7.024–8.658 s on Windows and 5.582–6.386 s on
WSL2; there was no observed upward growth across these nine batches. These
numbers are diagnostic samples, not a performance SLA or proof of fairness
under concurrent hosts. Temporary databases were removed after each run.

Still open: simultaneous Server/Connector hosts, a real slow consumer,
physical filesystem-full/WAL-pinned campaigns, provider effects and a
statistically controlled performance benchmark. This does not close TK-40,
TK-41 or J08 (100,000 Server agents is a different scenario).

After parameterizing the reusable probe and adding a four-row regression
test, the unchanged default 100k campaign was rerun on the current script.
Windows Python 3.13.1 completed in 77.141 s (76.511 s for 99k normal rows,
0.376 s reopen; 10k batches 7.147–8.389 s). WSL2 Python 3.13.14 completed
in 54.787 s (54.300 s normal, 0.153 s reopen; batches 4.897–6.045 s).
Both again reported 12,668,928 DB, 1,091,832 WAL and 32,768 SHM bytes,
with 100,000 durable operation rows and successful saturation/reopen checks.
`tests/test_profile_journal_admission.py` passed on both local systems.
The small probe test also passed with Python 3.11 and 3.12 on both systems
(WSL2/3.12 explicitly imports `src`). Full Python 3.13 suites passed on the
current tree: Windows 444 passed/73 skipped and WSL2 503 passed/14 skipped,
each with the expected injected legacy Pi thread warning.
