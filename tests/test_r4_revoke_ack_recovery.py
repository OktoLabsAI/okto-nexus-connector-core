"""Lost revoke ACK is recovered only from the exact committed fence row."""
import asyncio
from dataclasses import replace

import pytest
from nexus_connector_core import CoreError, ShutdownPolicy, TurnOperation
from test_runtime import FakeClock, make_runtime
from test_r4_runtime_leases import attempt, grant, open_session


@pytest.mark.parametrize("mismatch", [None, "connection_generation", "owner_generation",
                                      "authorization_revision", "configuration_revision", "revoked"])
def test_revoke_ack_recovery_compares_complete_durable_row(tmp_path, mismatch):
    async def scenario():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock, lease_poll_seconds=3600)
        original_cas, original_read = journal.cas_session_lease, journal.get_session_lease
        writes = []
        async def lost_ack(*args, **kwargs):
            writes.append(kwargs)
            await original_cas(*args, **kwargs)
            raise CoreError("CONFIRMATION_LOST", "test_revoke", possible_effect=True)
        try:
            req = await attempt(runtime, clock)
            application = await runtime.install_r4_lease(req, grant(req))
            await open_session(runtime, application.context)
            base = application.context
            journal.cas_session_lease = lost_ack
            with pytest.raises(CoreError, match="CONFIRMATION_LOST"):
                await runtime.revoke_r4_lease(base, authorization_revision=2)
            async def read(*args, **kwargs):
                row = await original_read(*args, **kwargs)
                if mismatch == "revoked":
                    return replace(row, revoked=False)
                if mismatch is not None:
                    return replace(row, **{mismatch: getattr(row, mismatch) + 1})
                return row
            journal.get_session_lease = read
            if mismatch is None:
                recovered = await runtime.revoke_r4_lease(base, authorization_revision=2)
                assert recovered.acknowledgement["application_stage"] == "REVOKED"
            else:
                with pytest.raises(CoreError, match="STALE_GENERATION"):
                    await runtime.revoke_r4_lease(base, authorization_revision=2)
            with pytest.raises(CoreError):
                await runtime.submit(TurnOperation("old", "session", "Forbidden"), base)
            assert factory.native.sent == [] and factory.open_count == 1
            assert len(writes) == 1
        finally:
            journal.get_session_lease = original_read
            journal.cas_session_lease = original_cas
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
    asyncio.run(scenario())
