# K10.1 journal crash boundaries — 2026-09-25

`tests/fixtures/journal_crash_peer.py` opens the reference SQLite journal in
a separate process and terminates with `os._exit(91)` without closing the
journal. The parent process reopens the same DB and checks the durable state.
The campaign runs on Windows and Ubuntu WSL2.

Covered cuts: before admission; after an uncommitted raw SQLite admission
insert (rollback required); after durable admission; after possible-effect
marker; after adapter proof of no write; after `OUTCOME_UNKNOWN`; after an
atomic terminal event/receipt commit; and after event ACK. The parent checks
that only committed facts survive, duplicate admission never becomes fresh
after a committed intent, uncertain effects remain non-retry-safe, terminal
event and receipt agree, and compacted ACKed sequences are not reused.

The uncommitted insert is test-only fault injection through a private DB
handle; production code continues to use the Journal port. These tests do
not cut at every instruction inside spawn/native pipe writes, simulate power
loss or disk corruption, or prove durability on every filesystem. Further
K10 process/effect fault campaigns and real host journal-adapter tests remain.
