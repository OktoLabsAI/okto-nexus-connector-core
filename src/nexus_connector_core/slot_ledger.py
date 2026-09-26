"""Installation-scoped durable owned-slot ledger shared across journals.

The trusted host must inject the same absolute local file path into every
Core instance belonging to one installation. A reservation is not proof that
its process is live; it remains occupied until the owning Core proves a
prelaunch refusal or observes stop through its native containment handle.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import time

from .journal import validate_claim_namespace, validate_claim_page
from .models import (CoreError, OperationKey, OwnedSlotPage,
                     OwnedSlotReservation, SessionKey)


class SQLiteOwnedSlotLedger:
    """A cross-process slot cap independent of per-executor journal files."""

    def __init__(self, path: str | Path, *, max_slots: int = 8,
                 max_storage_bytes: int = 64 * 1024 * 1024):
        path = Path(path)
        if not path.is_absolute():
            raise ValueError("owned-slot ledger needs an absolute local path")
        if (type(max_slots) is not int or not 1 <= max_slots <= 9223372036854775807 or
                type(max_storage_bytes) is not int or
                not 65536 <= max_storage_bytes <= 9223372036854775807):
            raise ValueError("invalid owned-slot ledger limits")
        self.path = path
        self.max_slots = max_slots
        self.max_storage_bytes = max_storage_bytes
        self._lock = asyncio.Lock()
        self._db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    mode = self._db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                except sqlite3.OperationalError as exc:
                    busy = ((getattr(exc, "sqlite_errorcode", 0) or 0) & 0xFF) in {
                        sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                    if not busy or time.monotonic() >= deadline:
                        raise
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                    continue
                if mode.lower() != "wal":
                    raise CoreError("JOURNAL_UNAVAILABLE", "slot_ledger_open")
                break
            self._db.execute("PRAGMA synchronous=FULL")
            page_size = self._db.execute("PRAGMA page_size").fetchone()[0]
            self._db.execute(
                f"PRAGMA max_page_count={max(1, max_storage_bytes // page_size)}")
            self._db.execute("PRAGMA wal_autocheckpoint=128")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS owned_slot_policy (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    max_slots INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owned_slot_reservations (
                    server_id TEXT NOT NULL,
                    executor_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    released INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(server_id, executor_id, session_id)
                );
                CREATE INDEX IF NOT EXISTS active_owned_slot_reservations
                    ON owned_slot_reservations(released);
            """)
            info = path.stat()
            self._storage_identity = (info.st_dev, info.st_ino)
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def _check_storage_identity(self) -> None:
        try:
            info = self.path.stat()
        except OSError as exc:
            raise CoreError("JOURNAL_UNAVAILABLE", "slot_ledger") from exc
        if (info.st_dev, info.st_ino) != self._storage_identity:
            raise CoreError("PROFILE_DRIFT", "slot_ledger")

    @staticmethod
    def _validate(key: OperationKey, session_id: str) -> None:
        if not isinstance(key, OperationKey):
            raise ValueError("invalid owned-slot identity")
        validate_claim_namespace(key.server_id, key.executor_id)
        if (type(key.operation_id) is not str or not key.operation_id or
                type(session_id) is not str or not session_id):
            raise ValueError("invalid owned-slot identity")

    def _rollback_if_active(self) -> None:
        if self._db.in_transaction:
            self._db.execute("ROLLBACK")

    async def reserve_owned_slot(self, key: OperationKey,
                                 session_id: str) -> None:
        """Reserve before native launch; ambiguity leaves the slot pinned."""
        self._validate(key, session_id)
        async with self._lock:
            self._check_storage_identity()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                policy = self._db.execute(
                    "SELECT max_slots FROM owned_slot_policy WHERE singleton=1"
                ).fetchone()
                if policy is None:
                    self._db.execute(
                        "INSERT INTO owned_slot_policy VALUES (1,?)",
                        (self.max_slots,))
                elif policy[0] != self.max_slots:
                    raise CoreError("PROFILE_DRIFT", "slot_ledger")
                existing = self._db.execute(
                    """SELECT 1 FROM owned_slot_reservations
                       WHERE server_id=? AND executor_id=? AND session_id=?""",
                    (key.server_id, key.executor_id, session_id)).fetchone()
                if existing is not None:
                    raise CoreError("SESSION_CONFLICT", "slot_ledger",
                                    possible_effect=True)
                occupied = self._db.execute(
                    "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
                ).fetchone()[0]
                if occupied >= self.max_slots:
                    raise CoreError("CAPACITY_EXCEEDED", "slot_ledger",
                                    retry_safe=True, operation_id=key.operation_id)
                self._db.execute(
                    "INSERT INTO owned_slot_reservations VALUES (?,?,?,?,0)",
                    (key.server_id, key.executor_id, session_id,
                     key.operation_id))
                self._db.execute("COMMIT")
            except BaseException as exc:
                self._rollback_if_active()
                if (isinstance(exc, sqlite3.Error) and
                        getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL):
                    raise CoreError("JOURNAL_FULL", "slot_ledger",
                                    retry_safe=True,
                                    operation_id=key.operation_id) from exc
                raise

    async def release_owned_slot(self, key: OperationKey,
                                 session_id: str) -> bool:
        """Trusted caller releases only after non-effect or observed stop."""
        self._validate(key, session_id)
        async with self._lock:
            self._check_storage_identity()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                policy = self._db.execute(
                    "SELECT max_slots FROM owned_slot_policy WHERE singleton=1"
                ).fetchone()
                if policy is None or policy[0] != self.max_slots:
                    raise CoreError("PROFILE_DRIFT", "slot_ledger_release")
                row = self._db.execute(
                    """SELECT operation_id,released FROM owned_slot_reservations
                       WHERE server_id=? AND executor_id=? AND session_id=?""",
                    (key.server_id, key.executor_id, session_id)).fetchone()
                if row is None or row[0] != key.operation_id:
                    raise CoreError("SESSION_CONFLICT", "slot_ledger_release")
                if not row[1]:
                    self._db.execute(
                        """UPDATE owned_slot_reservations SET released=1
                           WHERE server_id=? AND executor_id=? AND session_id=?""",
                        (key.server_id, key.executor_id, session_id))
                self._db.execute("COMMIT")
            except BaseException as exc:
                self._rollback_if_active()
                if (isinstance(exc, sqlite3.Error) and
                        getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL):
                    raise CoreError("JOURNAL_FULL", "slot_ledger_release",
                                    possible_effect=True,
                                    operation_id=key.operation_id) from exc
                raise
        return not bool(row[1])

    async def owned_slot_page(self, *, after_rowid: int = 0,
                              high_water_rowid: int | None = None,
                              limit: int = 128) -> OwnedSlotPage:
        """Read a bounded active-reservation page, not live process proof."""
        validate_claim_page(after_rowid, high_water_rowid, limit,
                            label="owned-slot")
        async with self._lock:
            self._check_storage_identity()
            policy = self._db.execute(
                "SELECT max_slots FROM owned_slot_policy WHERE singleton=1"
            ).fetchone()
            if policy is not None and policy[0] != self.max_slots:
                raise CoreError("PROFILE_DRIFT", "slot_ledger_page")
            if high_water_rowid is None:
                high_water_rowid = self._db.execute(
                    "SELECT COALESCE(MAX(rowid),0) FROM owned_slot_reservations"
                ).fetchone()[0]
            rows = self._db.execute(
                """SELECT rowid,server_id,executor_id,session_id,operation_id
                   FROM owned_slot_reservations
                   WHERE released=0 AND rowid>? AND rowid<=?
                   ORDER BY rowid LIMIT ?""",
                (after_rowid, high_water_rowid, limit + 1)).fetchall()
        page_rows = rows[:limit]
        return OwnedSlotPage(
            tuple(OwnedSlotReservation(SessionKey(server_id, executor_id,
                                                  session_id), operation_id)
                  for _, server_id, executor_id, session_id,
                  operation_id in page_rows),
            high_water_rowid,
            page_rows[-1][0] if len(rows) > limit else None)
