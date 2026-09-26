"""Read-only member comparison of two wheel or sdist archives."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import tarfile
import zipfile
from pathlib import Path


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _wheel(path: Path) -> dict[str, tuple[bytes, tuple[object, ...]]]:
    with zipfile.ZipFile(path) as archive:
        return {
            member.filename: (
                archive.read(member),
                (member.date_time, member.create_system, member.external_attr,
                 member.compress_type, member.flag_bits),
            )
            for member in archive.infolist()
        }


def _sdist(path: Path) -> dict[str, tuple[bytes, tuple[object, ...]]]:
    with tarfile.open(path, "r:gz") as archive:
        return {
            member.name: (
                archive.extractfile(member).read() if member.isfile() else b"",
                (member.mode, member.mtime, member.uid, member.gid,
                 member.uname, member.gname, member.pax_headers),
            )
            for member in archive
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--show-text", action="store_true")
    args = parser.parse_args()
    if args.left.suffix == ".whl" and args.right.suffix == ".whl":
        left, right = _wheel(args.left), _wheel(args.right)
    elif args.left.name.endswith(".tar.gz") and args.right.name.endswith(".tar.gz"):
        left, right = _sdist(args.left), _sdist(args.right)
    else:
        parser.error("both files must be wheel or both sdist")
    different = False
    for name in sorted(left.keys() | right.keys()):
        if name not in left:
            different = True
            print(f"right only: {name}")
        elif name not in right:
            different = True
            print(f"left only: {name}")
        elif left[name][0] != right[name][0]:
            different = True
            print(f"content: {name}: {_digest(left[name][0])} != {_digest(right[name][0])}")
            if args.show_text and len(left[name][0]) + len(right[name][0]) < 200_000:
                try:
                    before = left[name][0].decode("utf-8").splitlines()
                    after = right[name][0].decode("utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                print("\n".join(difflib.unified_diff(before, after,
                                                     fromfile="left", tofile="right")))
        elif left[name][1] != right[name][1]:
            different = True
            print(f"metadata: {name}: {left[name][1]} != {right[name][1]}")
    if different:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
