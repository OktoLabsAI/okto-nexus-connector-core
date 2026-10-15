"""Overlap sharing is not a cache or an authorization decision."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from nexus_connector_core.validation_flights import overlapping_validation
from nexus_connector_core.build_identity import executable_build_identity


def test_overlapping_checks_share_io_but_later_calls_read_again():
    entered, release = threading.Event(), threading.Event()
    calls = []
    @overlapping_validation
    def check(path):
        calls.append(path)
        entered.set()
        assert release.wait(3)
        return len(calls)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(check, "installation")
        assert entered.wait(3)
        others = [pool.submit(check, "installation") for _ in range(3)]
        time.sleep(.05)
        release.set()
        assert [future.result(3) for future in [first, *others]] == [1] * 4
    assert check("installation") == 2


def test_different_installation_does_not_wait_for_blocked_check():
    entered, release = threading.Event(), threading.Event()
    @overlapping_validation
    def check(path):
        if path == "slow":
            entered.set()
            assert release.wait(3)
        return path
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(check, "slow")
        assert entered.wait(3)
        try:
            assert pool.submit(check, "other").result(1) == "other"
        finally:
            release.set()
        assert slow.result(3) == "slow"


def test_failure_is_not_cached():
    attempts = 0
    @overlapping_validation
    def check(path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("changed installation")
        return "fresh"
    with pytest.raises(ValueError):
        check("installation")
    assert check("installation") == "fresh"


def test_same_size_same_mtime_replacement_is_rehashed(tmp_path):
    import os
    path = tmp_path / "executable"
    path.write_bytes(b"original")
    old_stat = path.stat()
    original = executable_build_identity(executable=path)
    path.write_bytes(b"replaced")
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert executable_build_identity(executable=path) != original
