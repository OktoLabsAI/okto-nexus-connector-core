"""One-shot PC01 conversion of journal.py to the off-loop worker."""
import re
from pathlib import Path

path = Path("src/nexus_connector_core/journal.py")
source = path.read_text(encoding="utf-8")

source = source.replace(
    "from .protocol import canonical_json",
    "from .offloop import (ExecutorClosed, ExecutorFull, OffLoopExecutor)\nfrom .protocol import canonical_json", 1)

init_start = source.index("        self._lock = asyncio.Lock()")
init_end = source.index("    def _storage_status(self) -> StorageStatus:")
old_init = source[init_start:init_end]
new_init = (
    '        self._executor = OffLoopExecutor(name="core-journal-worker")\n'
    "        self._has_legacy_operations = False\n"
    "        self._storage_identity = None\n"
    "        self._executor.start(self._open_database)\n"
    "\n"
    "    def _open_database(self):\n"
    '        """Worker-side setup: the connection lives on the executor thread."""\n'
    "        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)\n"
    "        deadline = time.monotonic() + 5\n"
    "        while True:\n"
    "            try:\n"
    '                mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]\n'
    "            except sqlite3.OperationalError as exc:\n"
    '                busy = ((getattr(exc, "sqlite_errorcode", 0) or 0) & 0xFF) in {\n'
    "                    sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}\n"
    "                if not busy or time.monotonic() >= deadline:\n"
    "                    db.close()\n"
    "                    raise\n"
    "                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))\n"
    "                continue\n"
    '            if mode.lower() != "wal" and self.path != ":memory:":\n'
    "                db.close()\n"
    '                raise CoreError("JOURNAL_UNAVAILABLE", "journal_open")\n'
    "            break\n"
    '        db.execute("PRAGMA synchronous=FULL")\n'
    '        page_size = db.execute("PRAGMA page_size").fetchone()[0]\n'
    "        max_pages = max(1, self.limits.max_storage_bytes // page_size)\n"
    '        db.execute(f"PRAGMA max_page_count={max_pages}")\n'
)
body_start = old_init.index(
    '        self._db.execute(\n            f"PRAGMA journal_size_limit')
new_init += (
    old_init[body_start:].replace("self._db", "db").replace(
        "            self._storage_identity = (info.st_dev, info.st_ino)\n",
        "            self._storage_identity = (info.st_dev, info.st_ino)\n"
        "        return db\n"))
source = source[:init_start] + new_init + source[init_end:]

helper_sigs = [
    ("    def _storage_status(self) -> StorageStatus:",
     "    def _storage_status(self, db) -> StorageStatus:"),
    ("    def _get(self, key: OperationKey) -> OperationReceipt | None:",
     "    def _get(self, db, key: OperationKey) -> OperationReceipt | None:"),
    ("    def _checkpoint_wal_locked(self) -> tuple[int, int, int]:",
     "    def _checkpoint_wal_locked(self, db) -> tuple[int, int, int]:"),
    ("    def _rollback_if_active(self) -> None:",
     "    def _rollback_if_active(self, db) -> None:"),
    ("    def _require_storage_capacity(self, estimate_bytes: int, *, critical: bool,",
     "    def _require_storage_capacity(self, db, estimate_bytes: int, *, critical: bool,"),
    ("    def _recover_normal_storage(self, estimate_bytes: int, *, stage: str,",
     "    def _recover_normal_storage(self, db, estimate_bytes: int, *, stage: str,"),
    ("    def _stream(self, event: RuntimeEvent) -> tuple[int, int, int]:",
     "    def _stream(self, db, event: RuntimeEvent) -> tuple[int, int, int]:"),
    ("    def _reserve_event(self, event: RuntimeEvent, body: bytes) -> None:",
     "    def _reserve_event(self, db, event: RuntimeEvent, body: bytes) -> None:"),
    ("    def _normal_event_quota_full(self, event: RuntimeEvent, size: int) -> bool:",
     "    def _normal_event_quota_full(self, db, event: RuntimeEvent, size: int) -> bool:"),
    ("    def _apply_terminal_event(self, event: RuntimeEvent) -> None:",
     "    def _apply_terminal_event(self, db, event: RuntimeEvent) -> None:"),
    ("    def _compact_acked_locked(\n",
     "    def _compact_acked_locked(self, db,\n"),
]
for old, new in helper_sigs:
    if old not in source:
        raise SystemExit(f"missing anchor: {old[:60]!r}")
    source = source.replace(old, new)
source = source.replace(
    "    def _compact_acked_locked(self, db,\n            self, max_rows: int, *,",
    "    def _compact_acked_locked(self, db,\n            max_rows: int, *,")

for old, new in [
    ("self._get(", "self._get(db, "),
    ("self._storage_status()", "self._storage_status(db)"),
    ("self._checkpoint_wal_locked()", "self._checkpoint_wal_locked(db)"),
    ("self._rollback_if_active()", "self._rollback_if_active(db)"),
    ("self._require_storage_capacity(", "self._require_storage_capacity(db, "),
    ("self._recover_normal_storage(", "self._recover_normal_storage(db, "),
    ("self._stream(", "self._stream(db, "),
    ("self._reserve_event(", "self._reserve_event(db, "),
    ("self._normal_event_quota_full(", "self._normal_event_quota_full(db, "),
    ("self._apply_terminal_event(", "self._apply_terminal_event(db, "),
    ("self._compact_acked_locked(", "self._compact_acked_locked(db, "),
    ("self._db", "db"),
]:
    source = source.replace(old, new)
path.write_text(source, encoding="utf-8")

lines = source.splitlines(keepends=True)
LOCK = "        async with self._lock:\n"


def line_delta(text):
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
        elif ch == "#":
            break
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        i += 1
    return depth


def first_post_lock_statement(line_list, start, end):
    depth = 0
    for idx in range(start, end):
        text = line_list[idx]
        if (depth == 0 and text.strip() and
                text.startswith("        ") and
                not text.startswith("            ")):
            return idx
        depth += line_delta(text)
        if depth < 0:
            depth = 0
    return end


def is_boundary(idx):
    line = lines[idx]
    return (line.startswith("    def ") or line.startswith("    async def ")
            or line.startswith("    @staticmethod")
            or line.startswith("    @property")
            or line.startswith("    @classmethod"))


out = []
i = 0
converted = []
postlock = []
while i < len(lines):
    if lines[i].startswith("    async def "):
        header_end = i
        while not lines[header_end].rstrip("\n").endswith(":"):
            header_end += 1
        j = header_end + 1
        lock_at = None
        while j < len(lines) and not is_boundary(j):
            if lines[j] == LOCK:
                lock_at = j
                break
            j += 1
        if lock_at is None:
            out.append(lines[i])
            i += 1
            continue
        body_end = lock_at + 1
        while body_end < len(lines) and not is_boundary(body_end):
            body_end += 1
        post_start = first_post_lock_statement(lines, lock_at + 1, body_end)
        if post_start != body_end:
            postlock.append(
                re.match(r"    async def ([a-zA-Z_0-9]+)", lines[i]).group(1))
        trim_end = body_end
        while trim_end > lock_at + 1 and lines[trim_end - 1].strip() == "":
            trim_end -= 1
        out.extend(lines[i:lock_at])
        out.append("        def _worker_impl(db):\n")
        out.extend(lines[lock_at + 1:min(post_start, trim_end)])
        for b in lines[post_start:trim_end]:
            if b.strip() == "":
                out.append(b)
            else:
                out.append("    " + b)
        name = re.match(r"    async def ([a-zA-Z_0-9]+)", lines[i]).group(1)
        urgent = name in {"cas_session_lease", "record_not_sent",
                          "release_owned_slot"}
        out.append(
            f"        return await self._run(_worker_impl, urgent={urgent})\n\n")
        converted.append(name)
        i = body_end
        continue
    out.append(lines[i])
    i += 1

path.write_text("".join(out), encoding="utf-8")
print("converted:", len(converted))
print("with post-lock code:", postlock)
