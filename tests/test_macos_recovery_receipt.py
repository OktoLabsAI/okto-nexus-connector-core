"""Darwin stop receipts stay conservative across owner replacement."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nexus_connector_core.native.process import macos_recovery
from nexus_connector_core.native.process import recovery
from nexus_connector_core.models import SessionKey
from nexus_connector_core.process_launch import ProcessLaunchIdentity


IDENTITY = 'darwin-launchd:ai.oktolabs.nexus-owned.123.' + 'a' * 16


@pytest.fixture
def receipt_dir(tmp_path, monkeypatch):
    if sys.platform == 'win32':
        pytest.skip('POSIX descriptor-relative receipt store')
    monkeypatch.setattr(
        macos_recovery, '_directory',
        lambda: os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY))
    return tmp_path


def test_only_exact_guardian_stop_proof_releases_container(receipt_dir):
    assert macos_recovery.recover_receipt(IDENTITY) == 'UNKNOWN'
    macos_recovery.create_receipt(IDENTITY)
    assert macos_recovery.recover_receipt(IDENTITY) == 'UNKNOWN'
    macos_recovery.mark_stopped(IDENTITY)
    assert macos_recovery.recover_receipt(IDENTITY) == 'STOPPED'
    with pytest.raises(OSError, match='not empty'):
        macos_recovery.mark_stopped(IDENTITY)


@pytest.mark.parametrize('identity', [
    '', 'darwin-launchd:foreign.123.' + 'a' * 16,
    'darwin-launchd:ai.oktolabs.nexus-owned.123.' + 'a' * 15,
    'darwin-launchd:ai.oktolabs.nexus-owned.123.' + 'a' * 16 + '/child',
])
def test_invalid_identity_never_reads_a_receipt(receipt_dir, identity):
    assert macos_recovery.recover_receipt(identity) == 'UNKNOWN'
    with pytest.raises(ValueError):
        macos_recovery.create_receipt(identity)


def test_partial_or_unsafe_receipts_remain_unknown(receipt_dir):
    name = IDENTITY.split(':', 1)[1]
    path = receipt_dir / name
    path.write_bytes(b'nexus-darwin-tree-stopped')
    os.chmod(path, 0o600)
    assert macos_recovery.recover_receipt(IDENTITY) == 'UNKNOWN'
    path.write_bytes(macos_recovery._STOPPED)
    os.chmod(path, 0o644)
    assert macos_recovery.recover_receipt(IDENTITY) == 'UNKNOWN'
    os.chmod(path, 0o600)
    link = receipt_dir / 'second-link'
    os.link(path, link)
    assert macos_recovery.recover_receipt(IDENTITY) == 'UNKNOWN'
    link.unlink()
    path.unlink()
    path.symlink_to(Path('/dev/null'))
    assert macos_recovery.recover_receipt(IDENTITY) == 'UNKNOWN'


def test_planned_darwin_recovery_uses_the_exact_receipt():
    launch = ProcessLaunchIdentity(
        SessionKey('server', 'executor', 'session'), 'open', 2, 3,
        'darwin', 'darwin_launchd_coalition', IDENTITY, 'b' * 32)
    with (patch.object(recovery, 'sys', SimpleNamespace(platform='darwin')),
          patch.object(macos_recovery, 'recover_receipt', return_value='STOPPED') as read):
        assert recovery.recover_launch_container(launch) == 'STOPPED'
    read.assert_called_once_with(IDENTITY, timeout_seconds=5)
