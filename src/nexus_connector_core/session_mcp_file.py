"""Private, session-owned native config; never edits a harness global file."""
import json
import os
from pathlib import Path
import tempfile

from .models import CoreError


class SessionMCPFile:
    def __init__(self):
        self.directory = None
        self.path = None

    def __repr__(self):
        return 'SessionMCPFile(<protected>)'

    def create(self, configuration):
        self.directory = Path(tempfile.mkdtemp(prefix='okto-session-mcp-'))
        try:
            if os.name == 'nt':
                _protect_windows(self.directory)
            else:
                self.directory.chmod(0o700)
            self.path = self.directory / 'mcp.json'
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(configuration, stream, ensure_ascii=False)
            return str(self.path)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.path is not None:
            self.path.unlink(missing_ok=True)
        if self.directory is not None and self.directory.exists():
            self.directory.rmdir()


def _protect_windows(directory):
    import ctypes
    from ctypes import wintypes
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    apply = security.SetFileSecurityW
    apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    apply.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    # Protected DACL, inherited by child files, grants full access only to
    # OWNER RIGHTS. No dependency on localized account names or shell quoting.
    if not convert('D:P(A;OICI;FA;;;OW)', 1, ctypes.byref(descriptor), None):
        raise CoreError('WORKSPACE_UNAVAILABLE', 'mcp_private_configuration')
    try:
        if not apply(str(directory), 0x80000004, descriptor):
            raise CoreError('WORKSPACE_UNAVAILABLE', 'mcp_private_configuration')
    finally:
        kernel.LocalFree(descriptor)
