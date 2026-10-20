"""Independent passive reads retain atomic snapshots and owned cancellation."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading

import pytest

from nexus_connector_core import CoreError, DiscoveryCancelled, discover_installations
from nexus_connector_core import discovery
from nexus_connector_core.discovery_control import check_discovery_cancelled
from tests.regression.test_c11_audit import _LAB_BINARY, _binary_name


ADAPTERS = ("codex_app_server", "pi_rpc", "claude_stream")


def test_all_harnesses_start_independently_and_keep_catalog_order(tmp_path, monkeypatch):
    """Real passive binary reads overlap; no provider execution is needed."""
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("provider launched"))
    for name in ("codex", "pi", "claude"):
        path = tmp_path / _binary_name(name)
        path.write_bytes(_LAB_BINARY)
        path.chmod(0o755)
    barrier = threading.Barrier(3)
    observe = discovery.discover_path
    def together(adapter, **arguments):
        barrier.wait(timeout=5)
        return observe(adapter, **arguments)
    monkeypatch.setattr(discovery, "discover_path", together)
    inventory = discover_installations(adapter_ids=ADAPTERS,
        path_env=str(tmp_path), trusted_roots=(tmp_path,))
    assert tuple(item.adapter_id for item in inventory.candidates) == ADAPTERS
    assert all(item.trust == "selected" and item.build_identity for item in inventory.candidates)


def test_cancel_reaches_all_workers_and_joins_before_return(monkeypatch):
    ready = threading.Barrier(4)
    release = threading.Event()
    stop = threading.Event()
    finished = []
    def observe(adapter, **arguments):
        try:
            ready.wait(timeout=5)
            assert release.wait(timeout=5)
            check_discovery_cancelled()
            pytest.fail("worker lost the caller's cancellation scope")
        finally:
            finished.append(adapter)
    monkeypatch.setattr(discovery, "discover_path", observe)
    with ThreadPoolExecutor(max_workers=1) as callers:
        result = callers.submit(discover_installations, adapter_ids=ADAPTERS,
                                cancel_requested=stop.is_set)
        try:
            ready.wait(timeout=5)
            stop.set()
        finally:
            release.set()
        with pytest.raises(DiscoveryCancelled):
            result.result(timeout=5)
    assert set(finished) == set(ADAPTERS)


def test_failure_does_not_publish_partial_inventory_or_detach_other_readers(monkeypatch):
    ready = threading.Barrier(3)
    release = threading.Event()
    failed = threading.Event()
    finished = threading.Event()
    def observe(adapter, **arguments):
        ready.wait(timeout=5)
        if adapter == ADAPTERS[0]:
            failed.set()
            raise CoreError("PROFILE_DRIFT", "discovery")
        try:
            assert release.wait(timeout=5)
            return ()
        finally:
            finished.set()
    monkeypatch.setattr(discovery, "discover_path", observe)
    with ThreadPoolExecutor(max_workers=1) as callers:
        result = callers.submit(discover_installations, adapter_ids=ADAPTERS[:2])
        try:
            ready.wait(timeout=5)
            assert failed.wait(timeout=5)
            with pytest.raises(TimeoutError):
                result.result(timeout=0.05)
        finally:
            release.set()
        with pytest.raises(CoreError, match="PROFILE_DRIFT"):
            result.result(timeout=5)
    assert finished.is_set()


def test_submitted_readers_are_bounded_even_with_repeated_adapter_requests(monkeypatch):
    entered = threading.Barrier(4)
    release = threading.Event()
    submitted = []
    class Readers(ThreadPoolExecutor):
        def submit(self, *args, **kwargs):
            submitted.append(args)
            return super().submit(*args, **kwargs)
    calls = []
    lock = threading.Lock()
    def observe(adapter, **arguments):
        with lock:
            calls.append(adapter)
            index = len(calls)
        if index <= 3:
            entered.wait(timeout=5)
            assert release.wait(timeout=5)
        return ()
    monkeypatch.setattr(discovery, "ThreadPoolExecutor", Readers)
    monkeypatch.setattr(discovery, "discover_path", observe)
    with ThreadPoolExecutor(max_workers=1) as callers:
        result = callers.submit(discover_installations, adapter_ids=ADAPTERS * 4)
        try:
            entered.wait(timeout=5)
            assert len(submitted) == 3
        finally:
            release.set()
        assert result.result(timeout=5).candidates == ()
    assert len(calls) == len(submitted) == 12
