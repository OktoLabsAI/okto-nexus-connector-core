# K04/K10 process-level SQLite admission fairness — 2026-09-26

`tests/test_journal_multiprocess_fairness.py` launches four independent Python
processes against one Core-owned SQLite journal. A parent-created database
avoids conflating schema creation with concurrent admission. Each child opens
its own connection, waits for a start byte, then submits 20 or 8 unique
operations; only typed, retry-safe, no-effect `JOURNAL_FULL` refusals are
accepted. The peers import `nexus_connector_core` from this project's `src`,
not from the sibling Nexus application.

The first case gives three noisy sessions and one quiet Server a shared
12-row budget, with two global critical slots, one critical slot per Server,
and one per session. The noisy Server is limited to four normal rows total;
the quiet Server still gets two normal rows. Both can subsequently admit a
critical row. A further noisy critical row is refused at its Server cap, and
an already-admitted operation remains a duplicate at saturation. The second
case races four Server namespaces for only three global slots and verifies
exactly three durable rows, with 29 safe refusals and no oversubscription.
The third case races four critical writers across two Servers and four
sessions for six hard global slots. It verifies all six are consumed exactly
once without breaching either Server's four-row or any session's three-row
hard cap; 26 further requests receive safe refusals.

The three focused tests passed on Windows 11 and Ubuntu WSL2 under Python
3.11, 3.12 and 3.13 (18 test outcomes). WSL2/Python 3.12 used `PYTHONPATH=src`
to bypass a stale editable installation. This adds independent-process
contention to the earlier connection-level and sequential 100k-operation
evidence; it is not simultaneous production Server/Connector hosts, a
slow-consumer campaign, a physical disk-full trial, or a 100k-agent scenario.
The corresponding TK-40/TK-41/J08 gates remain open.

Packaging check: the sdist previously included test modules but omitted
their process fixtures. `MANIFEST.in` now includes the Core test fixture
Python files; the rebuilt sdist contains both this test and its peer script.
Running the three focused tests from a separately extracted Windows sdist
directory passed, with the peers importing that extracted package's `src`.
With the final files stable, full Python 3.13 suites passed: Windows
447 passed/73 skipped and WSL2 506 passed/14 skipped, each with the expected
injected legacy Pi thread warning.
