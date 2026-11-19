"""Identity checks used when observing a private native conversation file."""

import os
import stat
from pathlib import Path


def plain_path(path: Path, *, directory: bool) -> os.stat_result:
    observed = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(observed.st_mode)
            or getattr(observed, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or (not directory and observed.st_nlink != 1)):
        raise ValueError("Unsupported saved history location.")
    return observed


def file_identity(observed: os.stat_result) -> tuple[int, int]:
    return observed.st_dev, observed.st_ino


def file_version(observed: os.stat_result) -> tuple:
    return (*file_identity(observed), observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns)
