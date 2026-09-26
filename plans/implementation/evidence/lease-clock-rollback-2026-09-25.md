# K04/K10 lease clock rollback fence — 2026-09-25

The local runtime and standalone effect kernel now share a process-local
`RollbackFencedClock`. It observes the injected monotonic source under a lock.
If a sample decreases or is non-finite, subsequent samples permanently read
as expired. New non-cleanup effects and lease renewals fail before journal
admission/native write; existing lease watchers advance to expiry and owned
cleanup. A later apparent clock recovery cannot revive that lease. The scoped
native-action capability gate uses the same fence so a rollback cannot revive
handoff actions through that separate path.

Synthetic tests cover both standalone kernel admission and an open runtime
session: a backwards sample denies a turn without calling its native backend
or creating a receipt, rejects renewal even after the source rises again, and
allows the lease watcher to close the owned session. A separate test proves
that an already-used native-action grant stays revoked after rollback and
apparent recovery; the standalone kernel test also covers `NaN` and infinity.
The real monotonic OS
clock normally does not move backwards within a boot; the fence addresses an
injected/virtualized bad source without converting it into extra lease time.

This is process-local evidence only. It does not restore ownership after a
runtime restart or reboot, qualify host clocks across machines, or complete
the TK-19/40 platform and saturation scenarios. Durable receipts remain the
recovery source; restart ownership remains unknown until host reconciliation.
