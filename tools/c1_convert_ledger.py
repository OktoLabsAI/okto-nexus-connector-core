"""PC01: convert slot_ledger.py to the off-loop executor (hand-verified)."""
from pathlib import Path

path = Path("src/nexus_connector_core/slot_ledger.py")
source = path.read_text(encoding="utf-8")

source = source.replace(
    "from .journal import validate_claim_namespace, validate_claim_page",
    "from .offloop import (ExecutorClosed, ExecutorFull, OffLoopExecutor)\n"
    "from .journal import validate_claim_namespace, validate_claim_page", 1)
source = source.replace("import asyncio\n", "", 1)

init_start = source.index("        self._lock = asyncio.Lock()")
init_end = source.index("    def close(self) -> None:")
new_init = '''        self._executor = OffLoopExecutor(name="core-slot-ledger-worker")
        self._storage_identity = None
        self._executor.start(self._open_database)

    def _open_database(self):
        """Worker-side setup: the connection lives on the executor thread."""
        db = sqlite3.connect(str(self.path), isolation_level=None, timeout=5)
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
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
            db.execute("PRAGMA synchronous=FULL")
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(
                f"PRAGMA max_page_count={max(1, self.max_storage_bytes // page_size)}")
            db.execute("PRAGMA wal_autocheckpoint=128")
            db.executescript("""
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
            info = self.path.stat()
            self._storage_identity = (info.st_dev, info.st_ino)
        except BaseException:
            db.close()
            raise
        return db
'''
source = source[:init_start] + new_init + source[init_end:]

source = source.replace('''    def close(self) -> None:
        self._db.close()

    def _check_storage_identity(self) -> None:''',
'''    async def _run(self, impl, *, urgent: bool = True):
        try:
            future = self._executor.submit(impl, urgent=urgent)
        except ExecutorFull as exc:
            raise CoreError("JOURNAL_BUSY", "slot_ledger",
                            retry_safe=True) from exc
        except ExecutorClosed as exc:
            raise CoreError("JOURNAL_CLOSED", "slot_ledger",
                            retry_safe=True) from exc
        return await future

    def _run_sync(self, work, *, timeout: float = 30.0):
        return self._executor.run_sync(work, timeout=timeout)

    async def aclose(self, *, timeout: float = 10.0) -> str:
        return await self._executor.aclose(timeout=timeout)

    def close(self) -> None:
        self._executor.close(timeout=15.0)

    def _check_storage_identity(self, db) -> None:''')
source = source.replace(
    "    def _rollback_if_active(self) -> None:\n"
    "        if self._db.in_transaction:\n"
    '            self._db.execute("ROLLBACK")',
    "    def _rollback_if_active(self, db) -> None:\n"
    "        if db.in_transaction:\n"
    '            db.execute("ROLLBACK")')

# reserve_owned_slot
reserve_start = source.index('    async def reserve_owned_slot(')
reserve_end = source.index('    async def release_owned_slot(')
source = (source[:reserve_start] +
'''    async def reserve_owned_slot(self, key: OperationKey,
                                 session_id: str) -> None:
        """Reserve before native launch; ambiguity leaves the slot pinned."""
        self._validate(key, session_id)

        def _worker_impl(db):
            self._check_storage_identity(db)
            db.execute("BEGIN IMMEDIATE")
            try:
                policy = db.execute(
                    "SELECT max_slots FROM owned_slot_policy WHERE singleton=1"
                ).fetchone()
                if policy is None:
                    db.execute(
                        "INSERT INTO owned_slot_policy VALUES (1,?)",
                        (self.max_slots,))
                elif policy[0] != self.max_slots:
                    raise CoreError("PROFILE_DRIFT", "slot_ledger")
                existing = db.execute(
                    """SELECT 1 FROM owned_slot_reservations
                       WHERE server_id=? AND executor_id=? AND session_id=?""",
                    (key.server_id, key.executor_id, session_id)).fetchone()
                if existing is not None:
                    raise CoreError("SESSION_CONFLICT", "slot_ledger",
                                    possible_effect=True)
                occupied = db.execute(
                    "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
                ).fetchone()[0]
                if occupied >= self.max_slots:
                    raise CoreError("CAPACITY_EXCEEDED", "slot_ledger",
                                    retry_safe=True, operation_id=key.operation_id)
                db.execute(
                    "INSERT INTO owned_slot_reservations VALUES (?,?,?,?,0)",
                    (key.server_id, key.executor_id, session_id,
                     key.operation_id))
                db.execute("COMMIT")
            except BaseException as exc:
                self._rollback_if_active(db)
                if (isinstance(exc, sqlite3.Error) and
                        getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL):
                    raise CoreError("JOURNAL_FULL", "slot_ledger",
                                    retry_safe=True,
                                    operation_id=key.operation_id) from exc
                raise
        return await self._run(_worker_impl)

''' + source[reserve_end:])

release_start = source.index('    async def release_owned_slot(')
release_end = source.index('    async def owned_slot_page(')
source = (source[:release_start] +
'''    async def release_owned_slot(self, key: OperationKey,
                                 session_id: str) -> bool:
        """Trusted caller releases only after non-effect or observed stop."""
        self._validate(key, session_id)

        def _worker_impl(db):
            self._check_storage_identity(db)
            db.execute("BEGIN IMMEDIATE")
            try:
                policy = db.execute(
                    "SELECT max_slots FROM owned_slot_policy WHERE singleton=1"
                ).fetchone()
                if policy is None or policy[0] != self.max_slots:
                    raise CoreError("PROFILE_DRIFT", "slot_ledger_release")
                row = db.execute(
                    """SELECT operation_id,released FROM owned_slot_reservations
                       WHERE server_id=? AND executor_id=? AND session_id=?""",
                    (key.server_id, key.executor_id, session_id)).fetchone()
                if row is None or row[0] != key.operation_id:
                    raise CoreError("SESSION_CONFLICT", "slot_ledger_release")
                if not row[1]:
                    db.execute(
                        """UPDATE owned_slot_reservations SET released=1
                           WHERE server_id=? AND executor_id=? AND session_id=?""",
                        (key.server_id, key.executor_id, session_id))
                db.execute("COMMIT")
            except BaseException as exc:
                self._rollback_if_active(db)
                if (isinstance(exc, sqlite3.Error) and
                        getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL):
                    raise CoreError("JOURNAL_FULL", "slot_ledger_release",
                                    possible_effect=True,
                                    operation_id=key.operation_id) from exc
                raise
            return not bool(row[1])
        return await self._run(_worker_impl)

''' + source[release_end:])

page_start = source.index('    async def owned_slot_page(')
source = (source[:page_start] +
'''    async def owned_slot_page(self, *, after_rowid: int = 0,
                              high_water_rowid: int | None = None,
                              limit: int = 128) -> OwnedSlotPage:
        """Read a bounded active-reservation page, not live process proof."""
        validate_claim_page(after_rowid, high_water_rowid, limit,
                            label="owned-slot")

        def _worker_impl(db, high_water_rowid=high_water_rowid):
            self._check_storage_identity(db)
            policy = db.execute(
                "SELECT max_slots FROM owned_slot_policy WHERE singleton=1"
            ).fetchone()
            if policy is not None and policy[0] != self.max_slots:
                raise CoreError("PROFILE_DRIFT", "slot_ledger_page")
            if high_water_rowid is None:
                high_water_rowid = db.execute(
                    "SELECT COALESCE(MAX(rowid),0) FROM owned_slot_reservations"
                ).fetchone()[0]
            rows = db.execute(
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
        return await self._run(_worker_impl)
''')

path.write_text(source, encoding="utf-8")
print("slot_ledger converted")
