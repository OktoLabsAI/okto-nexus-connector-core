"""Only a guardian's complete, private receipt proves a drained owned tree."""
import os
import select
import signal
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux guardian receipt')


@pytest.fixture
def receipts(tmp_path, monkeypatch):
    from nexus_connector_core.native.process import linux_recovery
    tmp_path.chmod(0o700)
    monkeypatch.setattr(linux_recovery, '_directory', lambda: os.open(
        tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC))
    return linux_recovery, tmp_path


def test_receipt_requires_complete_commit_and_remains_idempotent(receipts):
    module, _ = receipts
    identity, descriptor = module.create_receipt()
    try:
        assert module.recover_receipt(identity) == 'UNKNOWN'
        module.mark_stopped(descriptor)
        assert module.recover_receipt(identity) == 'STOPPED'
        assert module.recover_receipt(identity) == 'STOPPED'
        assert module.recover_receipt('linux-guardian:' + '0' * 32) == 'UNKNOWN'
        assert module.recover_receipt('../escape') == 'UNKNOWN'
    finally:
        os.close(descriptor)


@pytest.mark.parametrize('damage', ['truncated', 'extra', 'permissions', 'symlink', 'hardlink'])
def test_damaged_or_untrusted_receipt_cannot_prove_stop(receipts, damage):
    module, root = receipts
    identity, descriptor = module.create_receipt()
    module.mark_stopped(descriptor)
    os.close(descriptor)
    receipt = root / identity.split(':')[1]
    if damage == 'truncated':
        receipt.write_bytes(module._STOPPED[:-1])
    elif damage == 'extra':
        receipt.write_bytes(module._STOPPED + b'x')
    elif damage == 'permissions':
        receipt.chmod(0o644)
    elif damage == 'symlink':
        target = root / 'target'
        receipt.rename(target)
        receipt.symlink_to(target)
    else:
        os.link(receipt, root / 'alias')
    assert module.recover_receipt(identity) == 'UNKNOWN'


def test_failed_directory_commit_closes_new_receipt(receipts, monkeypatch):
    module, root = receipts
    def fail(_):
        raise OSError('injected fsync failure')
    monkeypatch.setattr(module.os, 'fsync', fail)
    before = len(os.listdir('/proc/self/fd'))
    with pytest.raises(OSError, match='injected'):
        module.create_receipt()
    assert len(os.listdir('/proc/self/fd')) == before
    assert list(root.iterdir()) == []


def test_killed_guardian_does_not_fabricate_stop_from_pid_death(tmp_path):
    from nexus_connector_core.native.process import spawn_owned_process, snapshot_owned_process_birth
    from nexus_connector_core.native.process.recovery import recover_owned_container
    from nexus_connector_core.native.process.linux_process_guardian import pidfd_open, pidfd_send_signal
    process = spawn_owned_process([sys.executable, '-c',
        'import os,time; print(os.getpid(),flush=True); time.sleep(60)'],
        cwd=str(tmp_path), env=dict(os.environ), text=True)
    native_fd = guardian_fd = None
    try:
        assert select.select([process.stdout], [], [], 10)[0]
        native_fd = pidfd_open(int(process.stdout.readline()))
        guardian_fd = pidfd_open(process.pid)
        evidence = snapshot_owned_process_birth(process)
        pidfd_send_signal(guardian_fd, signal.SIGKILL)
        process.wait(timeout=5)
        assert not select.select([native_fd], [], [], 0)[0]
        assert recover_owned_container(evidence, stop=True, timeout_seconds=.05) == 'UNKNOWN'
        assert process.tree_stopped is False
    finally:
        if native_fd is not None:
            try:
                pidfd_send_signal(native_fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            assert select.select([native_fd], [], [], 5)[0]
            os.close(native_fd)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if guardian_fd is not None:
            os.close(guardian_fd)
        # This test deliberately destroys the sole producer of the proof.
        # Only the test's exact pidfd now proves its native child stopped.
        process._release_slot()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
