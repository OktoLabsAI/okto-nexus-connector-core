"""File digests are cached by path, size, mtime and inode (#82)."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

from nexus_connector_core import build_identity, discovery


@pytest.fixture(autouse=True)
def clean_cache():
    build_identity._digest_cache.clear()
    yield
    build_identity._digest_cache.clear()


def _count_opens(monkeypatch):
    opened = []
    original = Path.open

    def counting(self, *args, **kwargs):
        if args and args[0] == "rb":
            opened.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting)
    return opened


def test_unchanged_file_is_read_once(tmp_path, monkeypatch):
    monkeypatch.setattr(build_identity, "_digest_cache_enabled", lambda: True)
    path = tmp_path / "binary"
    path.write_bytes(b"native content")
    opened = _count_opens(monkeypatch)
    expected = "sha256:" + hashlib.sha256(b"native content").hexdigest()
    assert discovery.fingerprint(path) == expected
    assert discovery.fingerprint(path) == expected
    assert build_identity._file_digest(path) == expected
    assert build_identity.executable_build_identity(path) == \
        build_identity.executable_build_identity(path)
    assert opened == [str(path)]


def test_changed_size_or_mtime_is_read_again(tmp_path, monkeypatch):
    path = tmp_path / "binary"
    path.write_bytes(b"first")
    opened = _count_opens(monkeypatch)
    assert discovery.fingerprint(path) == "sha256:" + hashlib.sha256(b"first").hexdigest()
    path.write_bytes(b"second!")
    assert discovery.fingerprint(path) == "sha256:" + hashlib.sha256(b"second!").hexdigest()
    # Same size, new mtime.
    path.write_bytes(b"SECOND!")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert discovery.fingerprint(path) == "sha256:" + hashlib.sha256(b"SECOND!").hexdigest()
    assert len(opened) == 3


def test_replaced_file_with_new_inode_is_read_again(tmp_path, monkeypatch):
    path = tmp_path / "binary"
    path.write_bytes(b"AAAA")
    stat = path.stat()
    opened = _count_opens(monkeypatch)
    assert discovery.fingerprint(path) == "sha256:" + hashlib.sha256(b"AAAA").hexdigest()
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"BBBB")
    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    os.replace(replacement, path)
    assert path.stat().st_ino != stat.st_ino
    assert discovery.fingerprint(path) == "sha256:" + hashlib.sha256(b"BBBB").hexdigest()
    assert len(opened) == 2


def test_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(build_identity, "_digest_cache_enabled", lambda: True)
    for index in range(build_identity._DIGEST_CACHE_LIMIT + 5):
        path = tmp_path / f"file{index}"
        path.write_bytes(bytes([index]))
        build_identity._file_digest(path)
    assert len(build_identity._digest_cache) == build_identity._DIGEST_CACHE_LIMIT


def test_file_changed_during_read_is_not_cached(tmp_path, monkeypatch):
    path = tmp_path / "binary"
    path.write_bytes(b"before")
    original = build_identity._digest_key
    calls = []

    def changing(target):
        calls.append(target)
        if len(calls) == 2:  # the check after the read
            path.write_bytes(b"after the change")
        return original(target)

    monkeypatch.setattr(build_identity, "_digest_key", changing)
    build_identity._file_digest(path)
    assert not build_identity._digest_cache


def test_rewrite_that_restores_mtime_is_read_again(tmp_path, monkeypatch):
    path = tmp_path / "binary"
    path.write_bytes(b"original")
    old = path.stat()
    opened = _count_opens(monkeypatch)
    first = discovery.fingerprint(path)
    path.write_bytes(b"replaced")
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert discovery.fingerprint(path) != first
    assert len(opened) == 2


def test_windows_does_not_trust_the_stat_key(tmp_path, monkeypatch):
    # Windows keeps st_ctime (creation time) across a rewrite. Simulate that
    # with a stat key that ignores ctime, then force the Windows path.
    original = build_identity._digest_key

    def windows_key(target):
        key = original(target)
        return None if key is None else key[:4] + (0,)

    monkeypatch.setattr(build_identity, "_digest_key", windows_key)
    monkeypatch.setattr(sys, "platform", "win32")
    path = tmp_path / "binary"
    path.write_bytes(b"original")
    old = path.stat()
    key_before = windows_key(path)
    opened = _count_opens(monkeypatch)
    first = discovery.fingerprint(path)
    path.write_bytes(b"replaced")
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert windows_key(path) == key_before  # the stat key cannot see it
    assert discovery.fingerprint(path) == \
        "sha256:" + hashlib.sha256(b"replaced").hexdigest()
    assert discovery.fingerprint(path) != first
    assert len(opened) == 3
    assert not build_identity._digest_cache
