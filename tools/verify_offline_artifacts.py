"""Install both local distributions without an index in isolated environments.

The caller supplies a platform/Python-specific wheelhouse containing runtime
dependencies plus setuptools and wheel for the sdist build. This command never
downloads packages; it verifies only the current host interpreter/platform.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import venv


def verify(root: Path, wheelhouse: Path) -> None:
    root = root.resolve()
    wheelhouse = wheelhouse.resolve()
    if not wheelhouse.is_dir() or not any(wheelhouse.glob("*.whl")):
        raise ValueError("wheelhouse must contain local wheels")
    version = tomllib.loads((root / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]["version"]
    dist = root / "dist"
    artifacts = (
        dist / f"nexus_connector_core-{version}-py3-none-any.whl",
        dist / f"nexus_connector_core-{version}.tar.gz",
    )
    if not all(path.is_file() for path in artifacts):
        raise ValueError("build the matching wheel and sdist first")
    manifest = root / "src/nexus_connector_core/contracts/nxl/v1/manifest.json"
    manifest_sha = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    consumer = (root / "tools/consumer_smoke.py").read_text(encoding="utf-8")
    environment = os.environ.copy()
    environment.update(PIP_NO_INDEX="1", PIP_FIND_LINKS=str(wheelhouse),
                       PIP_DISABLE_PIP_VERSION_CHECK="1",
                       PIP_NO_CACHE_DIR="1")
    for artifact in artifacts:
        with tempfile.TemporaryDirectory(prefix="nexus-core-offline-") as directory:
            venv.create(directory, with_pip=True)
            python = Path(directory) / ("Scripts/python.exe" if sys.platform == "win32"
                                        else "bin/python")
            pip = [str(python), "-m", "pip", "install", "--no-index",
                   "--no-cache-dir",
                   "--find-links", str(wheelhouse)]
            if artifact.suffix == ".gz":
                subprocess.run([*pip, "--force-reinstall", "setuptools>=68", "wheel"],
                               check=True, env=environment)
            subprocess.run([*pip, "--no-build-isolation", str(artifact)],
                           check=True, env=environment)
            smoke = r"""
import importlib.metadata as md
from importlib.resources import files
from nexus_connector_core import LocalRuntimeCore, RuntimeCore
from nexus_connector_core.conformance import verify_contract_bundle
from nexus_connector_core.pi_extension_resource import pi_extension_path
assert md.version('nexus-connector-core') == __import__('sys').argv[1]
assert files('nexus_connector_core').joinpath('py.typed').is_file()
assert files('nexus_connector_core.native').joinpath(
    'codex_app_server_0_157_0.schemas.json').is_file()
assert pi_extension_path().is_file()
assert verify_contract_bundle(__import__('sys').argv[2],
    allow_development_partial=True).checked_files == 9
"""
            subprocess.run([str(python), "-I", "-c", smoke, version,
                            manifest_sha], cwd=directory, env=environment,
                           check=True)
            if artifact.suffix == ".whl":
                wheel_sha = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
                for role in ("embedded", "remote"):
                    result = subprocess.run(
                        [str(python), "-I", "-c", consumer, role,
                         manifest_sha, wheel_sha], cwd=directory,
                        env=environment, capture_output=True, text=True,
                        check=True)
                    if json.loads(result.stdout) != {
                            "role": role, "wheel_sha256": wheel_sha}:
                        raise RuntimeError("offline consumer used unexpected wheel")
            print(f"offline install and resources OK: {artifact.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        verify(args.root, args.wheelhouse)
    except ValueError as exc:
        parser.exit(1, f"offline artifact check: {exc}\n")


if __name__ == "__main__":
    main()
