"""Real loopback producers remain owned across timeouts and cancelled observers."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.native_action_socket import PiNativeActionOwner
from test_pi_extension_resource import _service, _exchange, Backend


def claim():
    return dict(action="handoff.claim", operation_id="original-id", session_id="session",
                capability_ref="native-cap:session", handoff_id="work", idempotency_key="key")


class HeldBackend(Backend):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False
    async def claim_handoff(self, request, context):
        self.calls.append(request.operation_id)
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"handoff_id": request.handoff_id, "claim_epoch": 1}


def test_observation_timeout_preserves_mutation_and_identity(monkeypatch):
    async def run():
        monkeypatch.setattr("nexus_connector_core.native_action_socket._TIMEOUT_S", .05)
        backend = HeldBackend()
        service, _ = _service(backend)
        port = await service.start()
        try:
            response = await _exchange(port, claim())
            assert response == dict(ok=False, code="OUTCOME_UNKNOWN", possible_effect=True,
                                    retry_safe=False, operation_id="original-id")
            assert service.pending_count == 1 and not backend.cancelled
            assert await service.close(timeout_seconds=.01) is False
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
            except (ConnectionError, OSError):
                pass
            else:
                # Windows may complete a queued TCP handshake after close.
                # The application must reject it without admitting an effect.
                try:
                    writer.write(json.dumps(claim() | {"operation_id": "late-id"}).encode() + b"\n")
                    await writer.drain()
                    assert await asyncio.wait_for(reader.read(), 2) == b""
                except (ConnectionError, OSError):
                    pass
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except (ConnectionError, OSError):
                        pass
                assert backend.calls == ['original-id']
            assert service.pending_count == 1
            backend.release.set()
            assert await service.close(timeout_seconds=2) is True
            assert backend.calls == ["original-id"] and not backend.cancelled
        finally:
            backend.release.set()
            await service.close(timeout_seconds=2)
    asyncio.run(run())


def test_cancelled_close_waiter_cannot_cancel_backend_or_lose_ownership():
    async def run():
        backend = HeldBackend()
        service, _ = _service(backend)
        port = await service.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(json.dumps(claim()).encode() + b"\n")
        await writer.drain()
        await asyncio.wait_for(backend.entered.wait(), 2)
        try:
            closing = asyncio.create_task(service.close(timeout_seconds=5))
            await asyncio.sleep(0)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert await asyncio.wait_for(reader.read(), 2) == b""
            assert service.pending_count == 1 and not backend.cancelled
            backend.release.set()
            assert await service.close(timeout_seconds=2)
            assert service.pending_count == 0
            with pytest.raises(RuntimeError):
                await service.start()
        finally:
            backend.release.set()
            writer.close()
            await writer.wait_closed()
            await service.close(timeout_seconds=2)
    asyncio.run(run())


def test_close_owns_listener_start_even_when_start_observer_is_cancelled(monkeypatch):
    async def run():
        original = asyncio.start_server
        entered, release = asyncio.Event(), asyncio.Event()
        servers = []
        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            server = await original(*args, **kwargs)
            servers.append(server)
            return server
        monkeypatch.setattr(asyncio, "start_server", held)
        service, _ = _service()
        starting = asyncio.create_task(service.start())
        await entered.wait()
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not await service.close(timeout_seconds=.01)
        release.set()
        assert await service.close(timeout_seconds=2)
        assert len(servers) == 1 and not servers[0].is_serving()
    asyncio.run(run())


def test_pending_effects_bound_admission_after_clients_time_out(monkeypatch):
    async def run():
        monkeypatch.setattr("nexus_connector_core.native_action_socket._TIMEOUT_S", .03)
        monkeypatch.setattr("nexus_connector_core.native_action_socket._MAX_ACTIVE_CONNECTIONS", 1)
        backend = HeldBackend()
        service, _ = _service(backend)
        port = await service.start()
        try:
            assert (await _exchange(port, claim()))["possible_effect"]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            assert await asyncio.wait_for(reader.read(), 2) == b""
            writer.close()
            await writer.wait_closed()
            assert backend.calls == ["original-id"] and service.pending_count == 1
        finally:
            backend.release.set()
            assert await service.close(timeout_seconds=2)
    asyncio.run(run())


def test_idle_client_is_closed_without_a_domain_effect(monkeypatch):
    async def run():
        service, backend = _service()
        accepted = asyncio.Event()
        original_accept = service._accept

        def accept(reader, writer):
            original_accept(reader, writer)
            assert writer in service._writers
            accepted.set()

        monkeypatch.setattr(service, "_accept", accept)
        port = await service.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        # A client-side TCP handshake does not prove server-side admission.
        # Exercise shutdown of an owned idle socket, not a queued handshake.
        await asyncio.wait_for(accepted.wait(), 2)
        assert await service.close(timeout_seconds=2)
        assert await asyncio.wait_for(reader.read(), 2) == b""
        assert not backend.calls
        assert not service._handlers and not service._writers
        writer.close()
        await writer.wait_closed()
    asyncio.run(run())


def test_pi_owner_starts_once_and_checks_prepared_secret_and_current_context():
    async def run():
        service, _ = _service()
        context = service._context_provider()
        current = [context]
        owner = PiNativeActionOwner(service._bridge, lambda: current[0],
                                    capability_ref="native-cap:session", session_id="session")
        prepared = SimpleNamespace(intent=SimpleNamespace(adapter_id="pi_rpc"),
                                   secret_refs=("native-cap:session",))
        try:
            with pytest.raises(CoreError):
                await owner.launch(SimpleNamespace(intent=prepared.intent, secret_refs=()), "session", context)
            a, b = await asyncio.gather(owner.launch(prepared, "session", context),
                                        owner.launch(prepared, "session", context))
            assert a == b and owner.session_key.session_id == "session"
            current[0] = replace(context, authorization_revision=context.authorization_revision + 1)
            with pytest.raises(CoreError):
                await owner.launch(prepared, "session", context)
            assert await owner.close(timeout_seconds=2)
            with pytest.raises(CoreError):
                await owner.launch(prepared, "session", current[0])
        finally:
            await owner.close(timeout_seconds=2)
    asyncio.run(run())
