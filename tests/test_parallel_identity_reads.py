"""Bounded reads preserve the published v3 content identity and stop ownership."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from nexus_connector_core import DiscoveryCancelled
from nexus_connector_core import build_identity as identity
from nexus_connector_core.discovery_control import discovery_scope


def fixture(tmp_path):
    node = tmp_path / "node.exe"
    node.write_bytes(b"node fixture")
    package = tmp_path / "package"
    package.mkdir()
    for name, value in {"00-first.txt": b"first", "01-second.txt": b"second",
                        "02-third.txt": b"third", "03-fourth.txt": b"fourth",
                        "package.json": b"{}"}.items():
        (package / name).write_bytes(value)
    return node, package


def test_out_of_order_reads_preserve_core_48_golden_identity(tmp_path, monkeypatch):
    node, package = fixture(tmp_path)
    original = identity._file_digest_counted
    later_finished = threading.Event()
    completion = []
    def digest(path, size):
        if path.name == "00-first.txt":
            assert later_finished.wait(3)
        value = original(path, size)
        completion.append(path.name)
        if path.name == "01-second.txt":
            later_finished.set()
        return value
    monkeypatch.setattr(identity, "_file_digest_counted", digest)
    assert identity.pi_build_identity(node, package) == (
        "sha256:49eef9e3906c3da6c367c801e9753f529f60867d7458547824fd68bb62d303a7")
    assert completion.index("01-second.txt") < completion.index("00-first.txt")


def test_passive_observation_and_admitted_open_hash_the_same_content(tmp_path):
    node, package = fixture(tmp_path)
    expected = identity.pi_build_identity(node, package)
    with discovery_scope(lambda: False):
        assert identity.pi_build_identity(node, package) == expected


@pytest.mark.parametrize("passive,expected", [(True, 2), (False, 4)])
def test_identity_reader_budget_and_join(tmp_path, monkeypatch, passive, expected):
    node, package = fixture(tmp_path)
    for index in range(40):
        (package / f"extra-{index}.txt").write_bytes(b"content")
    stopped, full, release = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    active = 0
    started = 0
    maximum = 0
    original = identity._file_digest_counted
    def digest(path, size):
        nonlocal active, started, maximum
        with lock:
            active += 1
            started += 1
            maximum = max(maximum, active)
            if active == expected:
                full.set()
        try:
            assert release.wait(3)
            return original(path, size)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(identity, "_file_digest_counted", digest)
    def discover():
        if passive:
            with discovery_scope(stopped.is_set):
                return identity.pi_build_identity(node, package)
        return identity.pi_build_identity(node, package)
    with ThreadPoolExecutor(max_workers=1) as caller:
        result = caller.submit(discover)
        try:
            assert full.wait(3)
            if passive:
                stopped.set()
        finally:
            release.set()
        if passive:
            with pytest.raises(DiscoveryCancelled):
                result.result(timeout=3)
        else:
            assert result.result(timeout=3).startswith("sha256:")
    assert maximum == expected and active == 0
    assert started >= expected


def test_byte_budget_is_reserved_before_worker_reads(tmp_path, monkeypatch):
    node, package = fixture(tmp_path)
    monkeypatch.setattr(identity, "_MAX_MANIFEST_BYTES", 0)
    monkeypatch.setattr(identity, "_file_digest_counted",
                        lambda *_: pytest.fail("An unreserved file was read"))
    with pytest.raises(ValueError, match="bounded size"):
        identity.pi_build_identity(node, package)
