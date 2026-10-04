"""Native Darwin process ABI shared by the owned-process backend.

Only the private ``libproc`` flavors already exercised natively on the
Intel macOS 26.4.1 host (see ``plans/implementation/evidence/``) are used:

- ``PROC_PIDTBSDINFO`` (flavor 3): ``struct proc_bsdinfo`` from XNU
  ``bsd/sys/proc_info.h``. The layout below matches the 176-byte response
  the native probes validated, including the ``start_sec``/``start_usec``
  birth pair used for identity revalidation.
- ``PROC_PIDCOALITIONINFO`` (flavor 20): ``struct proc_pidcoalitioninfo``
  from XNU ``bsd/sys/proc_info_private.h`` — two coalition ids (resource
  at index 0, jetsam at index 1, per ``osfmk/mach/coalition.h``) followed
  by three reserved ``uint64_t`` fields, 40 bytes total. A partial or
  future-sized response is never accepted as membership evidence.
- ``proc_listallpids``: bounded whole-table enumeration used by the census.
- ``kern.bootsessionuuid`` sysctl: boot identity for birth tokens.

This module is a dependency-free ABI helper: it is imported as a package
module by the observer side and loaded by file location inside the
isolated launchd guardian (``python -I``), so it must rely on the
standard library only and never on package-relative imports.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
from dataclasses import dataclass, field

__all__ = [
    "BsdInfo", "CoalitionInfo", "SIDL", "SRUN", "SSLEEP", "SSTOP", "SZOMB",
    "boot_session_hash", "CensusResult", "coalition_members", "coalition_pair",
    "enumerate_pids", "identity", "libproc",
]

#: XNU bsd/sys/proc.h process states (subset used for census/stop logic).
SIDL, SRUN, SSLEEP, SSTOP, SZOMB = 1, 2, 3, 4, 5

PROC_PIDTBSDINFO = 3
PROC_PIDCOALITIONINFO = 20


class BsdInfo(ctypes.Structure):
    """``struct proc_bsdinfo`` (flavor 3), validated natively 2026-10-02."""

    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
        'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in (
        'nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64),
                 ('start_usec', ctypes.c_uint64)]


class CoalitionInfo(ctypes.Structure):
    """``struct proc_pidcoalitioninfo`` (flavor 20): ids + reserved."""

    _fields_ = [('ids', ctypes.c_uint64 * 2), ('reserved', ctypes.c_uint64 * 3)]


assert ctypes.sizeof(CoalitionInfo) == 40

_LIBPROC: ctypes.CDLL | None = None


def libproc() -> ctypes.CDLL:
    """Load ``libproc`` once with explicit ABI declarations."""
    global _LIBPROC
    if _LIBPROC is None:
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                     ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.proc_listallpids.restype = ctypes.c_int
        _LIBPROC = lib
    return _LIBPROC


def identity(pid: int) -> dict:
    """Read one PID's birth/state; raise ``ProcessLookupError`` when gone.

    A successful read returns a dict with ``pid``, ``ppid``, ``pgid``,
    ``status`` and the immutable ``birth`` pair ``(start_sec, start_usec)``.
    Any response that is not the exact structure size, names a different
    PID, or carries an impossible birth timestamp is an error — never
    identity evidence.
    """
    info = BsdInfo()
    count = libproc().proc_pidinfo(pid, PROC_PIDTBSDINFO, 0,
                                   ctypes.byref(info), ctypes.sizeof(info))
    if count == 0:
        code = ctypes.get_errno() or errno.ESRCH
        raise OSError(code, os.strerror(code))
    if count != ctypes.sizeof(info) or info.pid != pid:
        raise OSError(errno.EIO,
                      f'proc_pidinfo flavor {PROC_PIDTBSDINFO} returned '
                      f'{count} bytes for pid {pid}')
    if info.start_sec <= 0 or info.start_usec >= 1_000_000:
        raise ValueError('invalid process birth timestamp')
    return dict(pid=info.pid, ppid=info.ppid, pgid=info.pgid,
                status=info.status, birth=(info.start_sec, info.start_usec))


def coalition_pair(pid: int) -> tuple[int, int]:
    """Read one PID's ``(resource, jetsam)`` coalition ids.

    The response must be exactly the documented 40-byte structure with both
    ids nonzero; anything else refuses membership rather than guessing.
    """
    info = CoalitionInfo()
    count = libproc().proc_pidinfo(pid, PROC_PIDCOALITIONINFO, 0,
                                   ctypes.byref(info), ctypes.sizeof(info))
    if count == 0:
        code = ctypes.get_errno() or errno.ESRCH
        raise OSError(code, os.strerror(code))
    if count != ctypes.sizeof(info):
        raise OSError(errno.EIO,
                      f'coalition ABI returned {count} bytes, expected '
                      f'{ctypes.sizeof(info)}')
    if not info.ids[0] or not info.ids[1]:
        raise ValueError('a nonzero resource and jetsam coalition are required')
    return (info.ids[0], info.ids[1])


def enumerate_pids() -> list[int]:
    """Enumerate the whole process table, growing the buffer when full."""
    lib = libproc()
    size = lib.proc_listallpids(None, 0)
    if size <= 0:
        raise OSError(ctypes.get_errno() or errno.EIO, 'proc_listallpids failed')
    capacity = size + 256
    for _ in range(4):
        buffer = (ctypes.c_int * capacity)()
        count = lib.proc_listallpids(buffer, ctypes.sizeof(buffer))
        if count < 0:
            raise OSError(ctypes.get_errno() or errno.EIO,
                          'proc_listallpids failed')
        if count <= capacity:
            return [pid for pid in buffer[:count] if pid > 0]
        capacity = count + 256
    raise OSError(errno.EIO, 'process table kept overflowing bounded reads')


@dataclass
class CensusResult:
    """One coalition census pass.

    ``members`` are live ``(pid, birth)`` pairs in the coalition. Any other
    true value in ``incomplete`` (unreadable scan), ``foreign_denied``
    (other-uid processes skipped, matching the qualified native evidence
    semantics), ``recycled_after_death`` (PIDs reused by foreign processes
    after their member's death was confirmed) or a nonempty ``members``
    list means the tree is not proven stopped; only a complete pass with
    empty ``members`` counts as empty.
    """

    members: list = field(default_factory=list)
    incomplete: bool = False
    foreign_denied: int = 0
    recycled_after_death: int = 0

    @property
    def empty(self) -> bool:
        return not self.incomplete and not self.members


def _census_with(enumerate_pids, identity_fn, coalition_fn, pair, *,
                 exclude=(), seen=None, confirmed_dead=None) -> CensusResult:
    """Census core over injectable readers (kept testable)."""
    result = CensusResult()
    excluded = set(exclude)
    for pid in enumerate_pids():
        if pid in excluded:
            continue
        try:
            info = identity_fn(pid)
        except ProcessLookupError:
            if seen is not None:
                seen.pop(pid, None)
            continue
        except OSError as exc:
            if exc.errno == errno.EPERM:
                if seen is not None and seen.get(pid) is not None:
                    if confirmed_dead is not None and pid in confirmed_dead:
                        # The member's death was already confirmed; this
                        # unreadable PID is a recycled foreign process.
                        result.recycled_after_death += 1
                        seen.pop(pid, None)
                    else:
                        result.incomplete = True
                else:
                    result.foreign_denied += 1
            else:
                result.incomplete = True
            continue
        except ValueError:
            result.incomplete = True
            continue
        if info['status'] == SZOMB:
            # Dead (unreaped) member: no longer a live member of the tree.
            if seen is not None and pid in seen:
                del seen[pid]
            continue
        try:
            member = coalition_fn(pid) == pair
        except ProcessLookupError:
            continue
        except (OSError, ValueError):
            result.incomplete = True
            continue
        if member:
            birth = tuple(info['birth'])
            result.members.append((pid, birth))
            if seen is not None:
                seen[pid] = birth
        elif seen is not None and pid in seen:
            del seen[pid]
    return result


def coalition_members(pair: tuple[int, int], *, exclude=(),
                       seen: dict | None = None,
                       confirmed_dead=None) -> CensusResult:
    """Bounded census of live processes in one coalition pair.

    Zombies are excluded (terminated but unreaped processes cannot fork or
    run). A PID that disappears mid-scan (``ESRCH``) is skipped. Processes
    of other users are unreadable (``EPERM``): they cannot be plain
    descendants — ``fork`` keeps the guardian's uid — so they are skipped
    exactly as in the qualified native evidence, unless the optional
    ``seen`` map shows a previously verified member became unreadable
    (a setuid transition or PID recycling), which marks the scan
    incomplete instead of fabricating an empty tree. Enumeration failure
    raises ``OSError`` and must be handled as an incomplete pass by the
    caller.
    """
    return _census_with(enumerate_pids, identity, coalition_pair, pair,
                        exclude=exclude, seen=seen,
                        confirmed_dead=confirmed_dead)


def boot_session_hash() -> str:
    """Stable hashed boot-session identity for birth tokens."""
    lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    query = lib.sysctlbyname
    query.argtypes = [ctypes.c_char_p, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p,
                      ctypes.c_size_t]
    query.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    size = ctypes.c_size_t(len(buffer))
    if query(b'kern.bootsessionuuid', buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), 'cannot read boot session identity')
    value = buffer.value.decode('ascii')
    if not value:
        raise ValueError('empty boot session identity')
    return hashlib.sha256(value.encode()).hexdigest()
