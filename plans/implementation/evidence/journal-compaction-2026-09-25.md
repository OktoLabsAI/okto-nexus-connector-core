# Durable event ACK and logical compaction — 2026-09-25

K04 partial evidence on Windows/Python 3.13. The Core-owned SQLite journal
persists a per-`(server_id, executor_id, session_id, stream_epoch)` sequence
high-water, Server durable-ingress ACK watermark and compacted watermark.
The trusted host may acknowledge only a contiguous, present prefix. Repeated
older ACKs cannot lower the watermark. `compact_acked` deletes only confirmed
event bodies in bounded transactions and decrements transactional global and
Server/executor logical quotas. It never deletes operation receipts. Replay
from a pruned cursor raises `EVENT_GAP` instead of silently omitting history;
the next sequence remains monotonic after compaction and restart. The public
`LocalRuntimeCore` facade exposes ACK and compaction without exposing SQLite.

Verification:

- `pytest -q tests/test_journal_compaction.py tests/test_events.py
  tests/test_journal_limits.py tests/test_runtime.py`: 30 passed.
- `pytest -q`: 188 passed, 66 skipped.
- `python -m build --wheel --sdist`: passed.
- `python tools/verify_wheel.py`: clean wheel/dependency installation and
  import, contract hashes, and no Nexus/Connector imports in packaged Python.

SHA-256: wheel
`772e021e357b3bd6f5d4aa7fe6d778e0d4a1eb64ce36c994c6dbaec1c78aacca`;
sdist `91ef154e5078ae89c1ddfb015edd5a5f34e8e3e223a4f4fda76608e1f2b71fa4`.

The ACK call is authority supplied by the host only after Server ingress
commit; Core does not authenticate the Server itself. This evidence is for
logical event payload/row accounting, not a proven cap on SQLite database or
WAL file size. Automatic maintenance at the threshold, operation receipt
retention/compaction policy, disk-full fault campaign, and multi-host ACK
integration remain open. TK-16/TK-18/J24 remain NOT_RUN at full scope.
