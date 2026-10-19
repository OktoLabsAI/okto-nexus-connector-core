"""Recovery through a durable owned container, never through a historical PID.

The host must fence the original owner before calling with stop=True. A name
is persisted only after an atomic contained launch. An absent Windows job
means its last member exited; live jobs are stopped through their exact handle.
Legacy births without a container name remain unknown.
On Linux the original guardian persists proof only after reaping every child;
recovery waits for that proof without signalling historical process IDs.
"""
import ctypes
from ctypes import wintypes as w
import sys
import time

from ...journal import validate_process_birth
from ...process_launch import validate_launch_identity


def recover_owned_container(evidence, *, stop=False, timeout_seconds=5):
    validate_process_birth(evidence)
    if not 0 <= timeout_seconds <= 30:
        raise ValueError('Invalid recovery wait')
    if sys.platform == 'linux' and evidence.platform == 'linux' and evidence.container_id:
        from .linux_recovery import recover_receipt
        # The original owner's pidfd makes its guardian drain automatically.
        # Observe that exact proof; never signal a historical/reused PID.
        return recover_receipt(evidence.container_id, timeout_seconds=timeout_seconds if stop else 0)
    if sys.platform == 'darwin' and evidence.platform == 'darwin' and evidence.container_id:
        from .macos_recovery import recover_receipt
        return recover_receipt(evidence.container_id, timeout_seconds=timeout_seconds if stop else 0)
    if sys.platform != 'win32' or evidence.platform != 'win32' or not evidence.container_id:
        return 'UNKNOWN'
    return _recover_windows_container(evidence.container_id, stop=stop, timeout_seconds=timeout_seconds)


def recover_launch_container(identity, *, timeout_seconds=5):
    """Called only under producer exclusion after its durable fence.

    A durable intent identifies the container before any child exists. This
    path never fabricates a birth/PID to reuse the historical-birth interface.
    Unknown platform evidence is retained, never inferred from a missing PID.
    """
    validate_launch_identity(identity)
    if not 0 <= timeout_seconds <= 30:
        raise ValueError('Invalid recovery wait')
    if identity.platform != sys.platform:
        return 'UNKNOWN'
    if sys.platform == 'win32':
        return _recover_windows_container(identity.container_id, stop=True, timeout_seconds=timeout_seconds)
    if sys.platform == 'linux':
        from .linux_recovery import recover_receipt
        return recover_receipt(identity.container_id, timeout_seconds=timeout_seconds)
    if sys.platform == 'darwin':
        from .macos_recovery import recover_receipt
        return recover_receipt(identity.container_id, timeout_seconds=timeout_seconds)
    return 'UNKNOWN'


def _recover_windows_container(container_id, *, stop, timeout_seconds):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    open_job = kernel.OpenJobObjectW
    open_job.argtypes, open_job.restype = [w.DWORD,w.BOOL,w.LPCWSTR], w.HANDLE
    close = kernel.CloseHandle
    close.argtypes, close.restype = [w.HANDLE], w.BOOL
    query = kernel.QueryInformationJobObject
    query.argtypes, query.restype = [w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p], w.BOOL
    terminate = kernel.TerminateJobObject
    terminate.argtypes, terminate.restype = [w.HANDLE,w.UINT], w.BOOL

    class Accounting(ctypes.Structure):
        _fields_ = [(name,ctypes.c_longlong) for name in ('user','kernel','period_user','period_kernel')] + [
            (name,w.DWORD) for name in ('faults','total','active','terminated')]

    handle = open_job(4 | (8 if stop else 0), False, container_id)
    if not handle:
        return 'STOPPED' if ctypes.get_last_error() == 2 else 'UNKNOWN'
    try:
        def active():
            facts = Accounting()
            if not query(handle, 1, ctypes.byref(facts), ctypes.sizeof(facts), None):
                raise ctypes.WinError(ctypes.get_last_error())
            return facts.active
        if not active():
            return 'STOPPED'
        if not stop:
            return 'RUNNING'
        if not terminate(handle, 1):
            return 'UNKNOWN'
        deadline = time.monotonic() + timeout_seconds
        while active():
            if time.monotonic() >= deadline:
                return 'STOPPING'
            time.sleep(.02)
        return 'STOPPED'
    except OSError:
        return 'UNKNOWN'
    finally:
        close(handle)
