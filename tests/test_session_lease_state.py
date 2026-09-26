"""Durable session-lease fence: journal CAS, restart and runtime wiring."""

import asyncio
import time

import pytest

from nexus_connector_core import CoreError, ExecutionContext, SessionKey
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import (
    InstallationCandidate, LaunchIntent, OpenOperation, SessionLeaseState,
    ShutdownPolicy,
)
from nexus_connector_core.runtime import LocalRuntimeCore


class FakeNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        pass

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


class FakeFactory:
    def __init__(self):
        self.native = FakeNative()

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


def context(actions=None, connection_generation=1, session_owner_generation=1,
            authorization_revision=1, lease_deadline=None):
    return ExecutionContext(
        "srv", "exe", "binding", "agent", "ws", authorization_revision, 1,
        connection_generation,
        lease_deadline if lease_deadline is not None else time.monotonic() + 60,
        frozenset(actions or {"runtime.open", "turn.submit", "runtime.close"}),
        session_owner_generation)


def make_runtime(journal, tmp_path):
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary")
    candidate = InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary), "explicit",
        "selected")
    return LocalRuntimeCore(journal, FakeFactory(),
                            candidates={"codex_app_server": candidate},
                            workspace_roots={"ws": str(tmp_path)})


def test_journal_seeds_lease_with_claim_and_cas_fences(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        key_operation = "open-op"
        session = "session-a"
        admitted, fresh = await journal.admit(
            _op(key_operation), "sha256:" + "1" * 64, session,
            claim_session=True, connection_generation=3,
            session_owner_generation=5, authorization_revision=2,
            configuration_revision=4)
        assert fresh and admitted.stage == "RECEIVED_DURABLE"
        lease = await journal.get_session_lease(SessionKey("srv", "exe", session))
        assert lease == SessionLeaseState(
            SessionKey("srv", "exe", session), 3, 5, 2, 4, False)
        renewed = await journal.cas_session_lease(
            SessionKey("srv", "exe", session),
            expected_connection_generation=3, connection_generation=4,
            owner_generation=5, authorization_revision=3,
            configuration_revision=4, revoked=False)
        assert renewed.connection_generation == 4 and not renewed.revoked
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await journal.cas_session_lease(
                SessionKey("srv", "exe", session),
                expected_connection_generation=3, connection_generation=5,
                owner_generation=5, authorization_revision=4,
                configuration_revision=4, revoked=False)
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await journal.cas_session_lease(
                SessionKey("srv", "exe", session),
                expected_connection_generation=4, connection_generation=5,
                owner_generation=5, authorization_revision=2,
                configuration_revision=4, revoked=False)
        revoked = await journal.cas_session_lease(
            SessionKey("srv", "exe", session),
            expected_connection_generation=4, connection_generation=4,
            owner_generation=5, authorization_revision=4,
            configuration_revision=4, revoked=True)
        assert revoked.revoked
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await journal.cas_session_lease(
                SessionKey("srv", "exe", session),
                expected_connection_generation=4, connection_generation=5,
                owner_generation=5, authorization_revision=5,
                configuration_revision=4, revoked=False)
        assert (await journal.get_session_lease(
            SessionKey("srv", "exe", session))).revoked
        journal.close()

    asyncio.run(run())


def test_journal_lease_requires_claim_and_rejects_bad_values(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        await journal.admit(_op("legacy-open"), "sha256:" + "1" * 64,
                            "legacy-session", claim_session=True)
        assert await journal.get_session_lease(
            SessionKey("srv", "exe", "legacy-session")) is None
        with pytest.raises(CoreError, match="SESSION_UNKNOWN"):
            await journal.cas_session_lease(
                SessionKey("srv", "exe", "legacy-session"),
                expected_connection_generation=1, connection_generation=2,
                owner_generation=1, authorization_revision=1,
                configuration_revision=1, revoked=False)
        for invalid in (0, -1, True, "3", 1.5, 2**63):
            with pytest.raises(ValueError):
                await journal.cas_session_lease(
                    SessionKey("srv", "exe", "legacy-session"),
                    expected_connection_generation=invalid,
                    connection_generation=2, owner_generation=1,
                    authorization_revision=1, configuration_revision=1,
                    revoked=False)
        with pytest.raises(ValueError):
            await journal.cas_session_lease(
                SessionKey("srv", "exe", "legacy-session"),
                expected_connection_generation=1, connection_generation=2,
                owner_generation=1, authorization_revision=1,
                configuration_revision=1, revoked="no")
        with pytest.raises(ValueError):
            await journal.admit(
                _op("half-revision-open"), "sha256:" + "1" * 64,
                "half-session", claim_session=True,
                connection_generation=1, session_owner_generation=1,
                authorization_revision=1)
        journal.close()

    asyncio.run(run())


def test_journal_lease_survives_reopen_and_fences_second_connection(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        first = SQLiteJournal(path)
        await first.admit(_op("open-op"), "sha256:" + "1" * 64, "session-a",
                          claim_session=True, connection_generation=7,
                          session_owner_generation=9,
                          authorization_revision=1, configuration_revision=1)
        first.close()
        second = SQLiteJournal(path)
        lease = await second.get_session_lease(SessionKey("srv", "exe", "session-a"))
        assert lease.connection_generation == 7 and not lease.revoked
        third = SQLiteJournal(path)
        renewed = await third.cas_session_lease(
            SessionKey("srv", "exe", "session-a"),
            expected_connection_generation=7, connection_generation=8,
            owner_generation=9, authorization_revision=2,
            configuration_revision=1, revoked=False)
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            # The durable row moved under the second connection: an older
            # expected generation must lose even in-process.
            await second.cas_session_lease(
                SessionKey("srv", "exe", "session-a"),
                expected_connection_generation=7, connection_generation=9,
                owner_generation=9, authorization_revision=3,
                configuration_revision=1, revoked=False)
        assert (await second.get_session_lease(
            SessionKey("srv", "exe", "session-a"))).connection_generation == 8
        assert renewed.connection_generation == 8
        second.close()
        third.close()

    asyncio.run(run())


def test_runtime_open_renew_revoke_update_durable_lease(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = make_runtime(journal, tmp_path)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        session = SessionKey("srv", "exe", "session")
        opening = await runtime.persisted_lease(session)
        assert opening is not None and opening.connection_generation == 1
        assert not opening.revoked and opening.authorization_revision == 1
        renewed = await runtime.renew_lease(
            session, context(connection_generation=2,
                             authorization_revision=2,
                             lease_deadline=time.monotonic() + 120),
            expected_connection_generation=1)
        assert renewed.ownership == "owned"
        assert (await runtime.persisted_lease(
            session)).connection_generation == 2
        await runtime.revoke_lease(
            session, context(connection_generation=2,
                             authorization_revision=3),
            expected_connection_generation=2)
        durable = await runtime.persisted_lease(session)
        assert durable.revoked and durable.authorization_revision == 3
        await runtime.shutdown(ShutdownPolicy())
        journal.close()
        # After a full restart the last durable fence is still knowable.
        reopened = SQLiteJournal(tmp_path / "journal.db")
        try:
            assert await reopened.get_session_lease(session) == durable
        finally:
            reopened.close()

    asyncio.run(run())


def test_runtime_renew_loses_to_durable_fence_moved_by_peer(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = make_runtime(journal, tmp_path)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        session = SessionKey("srv", "exe", "session")
        # A second Core instance sharing the journal advances the durable
        # lease behind this runtime's in-memory generation.
        peer = SQLiteJournal(tmp_path / "journal.db")
        await peer.cas_session_lease(
            session, expected_connection_generation=1,
            connection_generation=5, owner_generation=1,
            authorization_revision=2, configuration_revision=1,
            revoked=False)
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await runtime.renew_lease(
                session, context(connection_generation=2,
                                 authorization_revision=2,
                                 lease_deadline=time.monotonic() + 120),
                expected_connection_generation=1)
        # The in-memory generation was not promoted by the failed renewal.
        assert (await runtime.persisted_lease(
            session)).connection_generation == 5
        peer.close()
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def _op(operation_id):
    from nexus_connector_core import OperationKey
    return OperationKey("srv", "exe", operation_id)
