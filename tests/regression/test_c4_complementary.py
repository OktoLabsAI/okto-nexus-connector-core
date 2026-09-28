"""C4 complementary scenarios (C4T-11..53 layer) - combined faults.

Combined-failure tests required by C4-07.02 plus the scenario mappings
that close the acceptance matrix: each test names the C4T cases it
demonstrates in this layer; the rest map to recorded evidence in
plans/correction-c4/evidence/T01-T07.md.
"""

import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, LaunchIntent, OpenOperation, SessionKey, ShutdownPolicy,
    TurnOperation, create_runtime,
)
from nexus_connector_core.journal import SQLiteJournal

from tests.regression.test_c4_audit import (
    _CloseBlockedNative, _FailFirstCasJournal, _RetainedAdmitJournal,
    _candidate, _unused_env,
)
from tests.test_runtime import FakeClock, context


def _runtime_with(tmp_path, journal, native, **kwargs):
    class _Factory:
        async def open(self, prepared, session_id, auth, *, stream_epoch):
            return native

    return create_runtime(
        journal=journal, environment=_unused_env,
        candidates={"codex_app_server": _candidate(tmp_path)},
        workspace_roots={"ws": str(tmp_path)},
        native_factory=_Factory(), clock=kwargs.pop("clock", FakeClock()),
        lease_grace_seconds=0.0, lease_poll_seconds=0.01,
        reconnect_fence_seconds=0.2, cleanup_budget_seconds=0.2, **kwargs)


async def _open(runtime, clock, *, deadline=None):
    auth = replace(context(),
                   lease_deadline_monotonic=deadline or clock.now + 60)
    prepared = await runtime.prepare(
        LaunchIntent("agent", "ws", "codex_app_server"), auth)
    opened = await runtime.open(
        OpenOperation("open-op", "session", "epoch", prepared), auth)
    assert opened.stage == "SUBMITTED"
    return auth


def test_c4t50_storage_retained_close_blocked_force_still_dispatched(
        tmp_path):
    """C4T-50 (combined): retained admit + blocked close + force - the
    physical containment of the already-owned tree still dispatches, and
    no new work is admitted (C4T-11/12 share the same fault point)."""
    clock = FakeClock(100.0)

    async def run():
        journal = _RetainedAdmitJournal(tmp_path / "journal.db")
        native = _CloseBlockedNative()
        runtime = _runtime_with(tmp_path, journal, native, clock=clock)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = await _open(runtime, clock)
            clock.advance(200)  # expiry beyond every tolerance
            report = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=5)
            assert report.session_outcomes[key] == "unknown"
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.force_called.wait, 1.5), timeout=5), (
                "storage retention delayed containment")
            with pytest.raises(CoreError):
                await runtime.submit(
                    TurnOperation("late", "session", "x"),
                    replace(auth, lease_deadline_monotonic=clock.now + 5))
        finally:
            native.close_gate.set()
            journal.admit_release.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            journal.close()

    asyncio.run(run())


def test_c4t13_zero_shutdown_shortens_scheduled_force_deadline(tmp_path):
    """C4T-13 rewritten per C5-03.06: a force genuinely scheduled for a
    FAR deadline (first shutdown, long budget) is ANTICIPATED by a later
    zero-budget shutdown - two real requests with barriers, no tautology.
    """
    from tests.regression.test_c5_audit import _CloseBlockedForceNative

    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _CloseBlockedForceNative()  # close never confirms
        runtime = _runtime_with(tmp_path, journal, native, clock=clock)
        key = SessionKey("srv", "exe", "session")
        try:
            await _open(runtime, clock)
            started = time.monotonic()
            # 1) LONG budget: the force is scheduled ~40s out and the
            # worker is WAITING on that far deadline.
            first = asyncio.create_task(runtime.shutdown(
                ShutdownPolicy(drain_seconds=20.0, interrupt_seconds=20.0)))
            await asyncio.sleep(0.3)
            # 2) ZERO budget: must tighten to now and dispatch.
            second = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=5)
            assert second.session_outcomes[key] == "unknown"
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.contained.wait, 2.0), timeout=6), (
                "the scheduled force was not anticipated")
            assert time.monotonic() - started < 10
        finally:
            native.close_gate.set()
            try:
                await asyncio.wait_for(first, timeout=10)
            except BaseException:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())

def test_c4t35_late_renew_commit_does_not_reopen_revoked_session(tmp_path):
    """C4T-35: a late renew commit is applied conservatively (never
    reopening fences), revocation afterwards applies cleanly, and an
    ANCIENT renew context can never restore permissions."""
    clock = FakeClock(100.0)

    class _ReleaseJournal(SQLiteJournal):
        def __init__(self, path):
            super().__init__(path)
            self.hold = asyncio.Event()
            self.holding = False

        async def cas_session_lease(self, session, **kwargs):
            if not kwargs.get("revoked", False) and not self.holding:
                self.holding = True
                await self.hold.wait()
            return await super().cas_session_lease(session, **kwargs)

    async def run():
        journal = _ReleaseJournal(tmp_path / "journal.db")
        native = _CloseBlockedNative()
        native.close_gate.set()
        runtime = _runtime_with(tmp_path, journal, native, clock=clock)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = await _open(runtime, clock)
            renewing = asyncio.create_task(runtime.renew_lease(
                key, replace(auth, lease_deadline_monotonic=clock.now + 120,
                             authorization_revision=2),
                expected_connection_generation=auth.connection_generation))
            await asyncio.sleep(0.1)  # renew accepted, holding the CAS
            # While the unit is in flight, a revocation is conservatively
            # BUSY - never a blind concurrent CAS (C4T-34).
            with pytest.raises(CoreError) as busy:
                await runtime.revoke_lease(
                    key, replace(auth, authorization_revision=3),
                    expected_connection_generation=auth.connection_generation)
            assert busy.value.code == "REVOKE_BUSY"
            # Caller stops waiting; the unit commits LATE and the applier
            # applies revision 2 conservatively (lease still live).
            renewing.cancel()
            try:
                await renewing
            except BaseException:
                pass  # CancelledError or the timeout-converted BUSY
            journal.hold.set()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                binding = runtime._sessions.get(key)
                if binding is not None and                         binding.context.authorization_revision == 2:
                    break
                await asyncio.sleep(0.02)
            binding = runtime._sessions[key]
            assert binding.context.authorization_revision == 2
            assert not binding.revoked
            # Revocation now applies (no pending unit).
            await runtime.revoke_lease(
                key, replace(auth, authorization_revision=3),
                expected_connection_generation=auth.connection_generation)
            binding = runtime._sessions[key]
            assert binding.revoked
            assert binding.context.allowed_actions == frozenset()
            # An ANCIENT renew (older revision) never reopens the fence.
            with pytest.raises(CoreError) as stale:
                await runtime.renew_lease(
                    key, replace(auth, lease_deadline_monotonic=clock.now + 130,
                                 authorization_revision=2),
                    expected_connection_generation=auth.connection_generation)
            # A revoked binding refuses the ancient renew - the exact
            # code depends on which fence trips first, but NONE of them
            # reopens work admission.
            assert stale.value.code in {"AGENT_REVOKED", "STALE_GENERATION",
                                        "SESSION_UNKNOWN", "SESSION_CLOSING"}
            with pytest.raises(CoreError):
                await runtime.submit(
                    TurnOperation("post", "session", "x"), auth)
        finally:
            journal.hold.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


def test_c4t41_prior_algorithm_digests_never_qualify():
    """C4T-41: candidates recorded under v2/v3-partial digests do not
    qualify after the algorithm moved on; reprepare is required."""
    from nexus_connector_core.native.adapters import compatibility
    legacy = [
        "sha256:bc3b22f8927a334f75d4a5d824e7a280c105b4929910cd127b1d0173e4284914",
        "sha256:b454b39171e7428e721ecc01be6654c3608a9091d398c3d3d445897a91a67e43",
        "sha256:d4f09928e4a7043d1d6bd742a4ead3344d3b18b3990410b797ba65169a0cf583",
    ]
    for digest in legacy:
        assert not compatibility.qualified_build(
            "pi", "0.87.1", "win32", "x86_64", "sha256:" + "0" * 64,
            build_identity=digest)
    assert compatibility.qualified_build(
        "pi", "0.87.1", "win32", "x86_64", "sha256:" + "0" * 64,
        build_identity="sha256:caf8bfad84ea26a7c8eaee06e0cde3dd7e34ef05e00dbebc348dfb3f22de487b")


def test_c4t38_duplicate_versions_keep_distinct_topology(tmp_path):
    """C4T-38: two importers resolving different versions of one name
    never collide in the logical manifest layout."""
    import json
    from nexus_connector_core.build_identity import pi_build_identity
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"n")
    node.chmod(0o755)
    nm = install / "node_modules"
    pkg = nm / "@earendil-works" / "pi-coding-agent"
    (pkg / "dist" / "bundle").mkdir(parents=True)
    (pkg / "dist" / "bundle" / "cli.js").write_bytes(b"cli")
    (pkg / "package.json").write_text(json.dumps(
        {"name": "pi", "version": "0.87.1",
         "dependencies": {"a": "1", "b": "1"}}))
    for letter in ("a", "b"):
        dep = nm / letter
        dep.mkdir(parents=True)
        (dep / "package.json").write_text(json.dumps(
            {"name": letter, "version": "1",
             "dependencies": {"shared": "1"}}))
        nested = dep / "node_modules" / "shared"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text(
            '{"name":"shared","version":"1"}')
        (nested / "index.js").write_bytes(letter.encode())  # distinct bytes
    base = pi_build_identity(node, pkg)
    (nm / "b" / "node_modules" / "shared" / "index.js").write_bytes(b"z")
    changed = pi_build_identity(node, pkg)
    assert changed != base, "topology collision hid one version's content"


def test_c4t45_enumeration_caps_stop_before_materializing(tmp_path):
    """C4T-45: many empty directories cannot bypass the enumeration
    bounds; a small cap refuses early."""
    import nexus_connector_core.build_identity as bi
    from nexus_connector_core.build_identity import pi_build_identity
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"n")
    node.chmod(0o755)
    pkg = install / "node_modules" / "@earendil-works" / "pi-coding-agent"
    (pkg / "dist" / "bundle").mkdir(parents=True)
    (pkg / "dist" / "bundle" / "cli.js").write_bytes(b"cli")
    (pkg / "package.json").write_text('{"name":"pi","version":"1"}')
    for i in range(500):
        (pkg / f"empty{i}").mkdir()
    old_dirs = bi._MAX_DIRECTORIES
    try:
        bi._MAX_DIRECTORIES = 50
        with pytest.raises(ValueError):
            pi_build_identity(node, pkg)
    finally:
        bi._MAX_DIRECTORIES = old_dirs
