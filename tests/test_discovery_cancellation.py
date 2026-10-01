"""Passive cancellation neither returns partial trust nor contaminates other work."""
import hashlib
import io
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from nexus_connector_core import DiscoveryCancelled, discover_installations
from nexus_connector_core import build_identity, discovery
from nexus_connector_core.discovery_control import discovery_scope


@pytest.mark.parametrize("kind", ["fingerprint", "executable_digest", "counted_digest"])
def test_cancellation_closes_reader_before_returning_a_partial_digest(tmp_path, monkeypatch, kind):
    path = tmp_path / "binary"
    path.write_bytes(b"native content")
    stopped = threading.Event()
    reads = []
    class Reader(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            value = super().read(size)
            stopped.set()
            return value
    stream = Reader(b"native content")
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", lambda *_args, **_kwargs: stream)
        with pytest.raises(DiscoveryCancelled), discovery_scope(stopped.is_set):
            if kind == "fingerprint":
                discovery.fingerprint(path)
            elif kind == "executable_digest":
                build_identity._file_digest(path)
            else:
                build_identity._file_digest_counted(path, 14)
    assert len(reads) == 1 and stream.closed
    # An exceptional scope cannot stop later ordinary runtime validation.
    assert discovery.fingerprint(path) == "sha256:" + hashlib.sha256(b"native content").hexdigest()


def test_preexisting_stop_never_enters_discovery(monkeypatch):
    monkeypatch.setattr(discovery, "discover_path", lambda *_a, **_kw: pytest.fail("unexpected read"))
    with pytest.raises(DiscoveryCancelled):
        discover_installations(cancel_requested=lambda: True)


def test_final_checkpoint_refuses_partial_inventory(monkeypatch):
    stopped = threading.Event()
    def observed(*_args, **_kwargs):
        stopped.set()
        return (object(),)
    monkeypatch.setattr(discovery, "discover_path", observed)
    with pytest.raises(DiscoveryCancelled):
        discover_installations(adapter_ids=("codex_app_server",), cancel_requested=stopped.is_set)


def test_context_is_independent_between_threads(tmp_path):
    path = tmp_path / "binary"
    path.write_bytes(b"same bytes")
    barrier = threading.Barrier(2)
    def run(cancel):
        try:
            with discovery_scope(None):
                barrier.wait(timeout=3)
                with discovery_scope(lambda: cancel):
                    return discovery.fingerprint(path)
        except DiscoveryCancelled:
            return "cancelled"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(run, True), pool.submit(run, False)
        assert first.result(timeout=3) == "cancelled"
        assert second.result(timeout=3) == discovery.fingerprint(path)


def test_directory_enumeration_closes_on_cancellation(tmp_path, monkeypatch):
    stopped = threading.Event()
    class Entries:
        closed = False
        def __iter__(self):
            stopped.set()
            yield type("Entry", (), {"name": "file"})()
            pytest.fail("Enumeration continued after cancellation")
        def close(self):
            self.closed = True
    entries = Entries()
    monkeypatch.setattr(build_identity.os, "scandir", lambda _: entries)
    with pytest.raises(DiscoveryCancelled), discovery_scope(stopped.is_set):
        build_identity._iter_tree_files(tmp_path)
    assert entries.closed


def test_invalid_callback_is_rejected():
    with pytest.raises(TypeError, match="cancel_requested"):
        discover_installations(cancel_requested=True)
