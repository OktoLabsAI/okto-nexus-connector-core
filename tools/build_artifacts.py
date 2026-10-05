"""Build Core artifacts with a stable archive timestamp.

This pins archive timestamps, not the versions of build-time dependencies.
Release provenance still requires a locked build environment and CI evidence.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path


# 2026-01-01 00:00:00 UTC. A fixed value makes local rebuilds comparable.
SOURCE_DATE_EPOCH = "1767225600"


def _normalized_generated_text(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _normalize_wheel(path: Path) -> None:
    """Canonicalize archive metadata and regenerate hashes for changed metadata."""
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".whl", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            entries = [(member.filename, source.read(member)) for member in source.infolist()]
            records: list[tuple[str, str, str]] = []
            record_name: str | None = None
            for name, data in entries:
                if name.endswith(".dist-info/METADATA"):
                    data = _normalized_generated_text(data)
                if name.endswith(".dist-info/RECORD"):
                    record_name = name
                    continue
                digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
                records.append((name, f"sha256={digest}", str(len(data))))
                _write_wheel_member(target, name, data)
            if record_name is None:
                raise RuntimeError("wheel RECORD is missing")
            record_text = io.StringIO(newline="")
            writer = csv.writer(record_text, lineterminator="\n")
            writer.writerows([*records, (record_name, "", "")])
            _write_wheel_member(target, record_name, record_text.getvalue().encode("utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_wheel_member(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    member = zipfile.ZipInfo(name, time.gmtime(int(SOURCE_DATE_EPOCH))[:6])
    member.create_system = 3
    member.external_attr = 0o100644 << 16
    member.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(member, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _normalize_sdist(path: Path) -> None:
    """Remove filesystem/build-time metadata from the generated tarball."""
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tar.gz", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with tarfile.open(path, "r:gz") as source, temporary.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=int(SOURCE_DATE_EPOCH)) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as target:
                    for member in source:
                        data = source.extractfile(member).read() if member.isfile() else None
                        if data is not None and (member.name.endswith("/PKG-INFO") or
                                                 member.name.endswith("/setup.cfg")):
                            data = _normalized_generated_text(data)
                            member.size = len(data)
                        member.mtime = int(SOURCE_DATE_EPOCH)
                        member.uid = member.gid = 0
                        member.uname = member.gname = ""
                        member.mode = 0o644 if member.isfile() else 0o755
                        member.pax_headers = {
                            key: value for key, value in member.pax_headers.items()
                            if key not in {"mtime", "atime", "ctime"}
                        }
                        target.addfile(member, io.BytesIO(data) if data is not None else None)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    outdir = args.outdir.resolve()
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(outdir)],
        cwd=root,
        env=env,
        check=True,
    )
    sdists = sorted(outdir.glob("okto_nexus_connector_core-*.tar.gz"))
    wheels = sorted(outdir.glob("okto_nexus_connector_core-*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        raise RuntimeError("expected exactly one Core wheel and sdist in output directory")
    _normalize_wheel(wheels[0])
    _normalize_sdist(sdists[0])


if __name__ == "__main__":
    main()
