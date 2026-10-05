"""Read-only release artifact gate; never uploads or creates credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

PROJECT_NAME = "okto-nexus-connector-core"
DIST_NAME = "okto_nexus_connector_core"
_VERSION = re.compile(r"\d+\.\d+\.\d+(?:\.dev\d+)?\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def validate(
    root: Path, version: str, *, expected_wheel: str | None = None,
    expected_sdist: str | None = None, allow_development: bool = False,
) -> dict[str, str | bool]:
    if (not _VERSION.fullmatch(version) or
            (".dev" in version and not allow_development)):
        raise ValueError("only an explicitly reviewed stable version is publishable")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if (project.get("name") != PROJECT_NAME or project.get("version") != version or
            project.get("readme") != "README.md" or
            not isinstance(project.get("license"), str) or
            not (root / "LICENSE").is_file()):
        raise ValueError("project name, version, README or license is inconsistent")
    wheel = root / "dist" / f"{DIST_NAME}-{version}-py3-none-any.whl"
    sdist = root / "dist" / f"{DIST_NAME}-{version}.tar.gz"
    if (not wheel.is_file() or not sdist.is_file() or
            len(list((root / "dist").glob(f"{DIST_NAME}-*.whl"))) != 1 or
            len(list((root / "dist").glob(f"{DIST_NAME}-*.tar.gz"))) != 1):
        raise ValueError("expected exactly the selected wheel and sdist")
    hashes = {"wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "sdist_sha256": hashlib.sha256(sdist.read_bytes()).hexdigest()}
    for label, expected in (("wheel_sha256", expected_wheel),
                            ("sdist_sha256", expected_sdist)):
        if expected is not None and (not _SHA256.fullmatch(expected) or
                                     expected != hashes[label]):
            raise ValueError(f"{label} does not match the approved hash")
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist()
                          if name.endswith(".dist-info/METADATA")]
        license_names = [name for name in archive.namelist()
                         if name.endswith(".dist-info/licenses/LICENSE")]
        if len(metadata_names) != 1 or len(license_names) != 1 or archive.read(
                license_names[0]) != (root / "LICENSE").read_bytes():
            raise ValueError("wheel METADATA or license missing, ambiguous or changed")
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
    if (metadata.get("Name") != PROJECT_NAME or
            metadata.get("Version") != version or
            metadata.get("License-Expression") != project["license"] or
            metadata.get("Description-Content-Type") != "text/markdown" or
            not metadata.get_payload().strip()):
        raise ValueError("wheel name/version/long description is inconsistent")
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getnames()
        licenses = [name for name in members if name.endswith("/LICENSE")]
        if (len(licenses) != 1 or
                archive.extractfile(licenses[0]).read() != (root / "LICENSE").read_bytes() or
                not any(name.endswith("/README.md") for name in members)):
            raise ValueError("sdist license or README missing")
    return {"version": version, "publishable": ".dev" not in version, **hashes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--version", required=True)
    parser.add_argument("--wheel-sha256")
    parser.add_argument("--sdist-sha256")
    parser.add_argument("--allow-development", action="store_true")
    args = parser.parse_args()
    try:
        report = validate(
            args.root, args.version, expected_wheel=args.wheel_sha256,
            expected_sdist=args.sdist_sha256,
            allow_development=args.allow_development)
    except ValueError as exc:
        parser.exit(1, f"release gate: {exc}\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
