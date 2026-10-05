"""Generate a CycloneDX SBOM for the built Core wheel and its runtime deps.

The generator runs in a different temporary venv from the wheel under audit.
Neither environment inherits PYTHONPATH/PYTHONHOME/VIRTUAL_ENV from the caller.
This is an inventory, not a legal approval of dependency licenses.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


GENERATOR = "cyclonedx-bom==7.3.1"
REQUIRED = {"okto-nexus-connector-core", "rfc8785", "jsonschema"}


def _python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _clean_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}


def _run(argv: list[str], *, env: dict[str, str]) -> None:
    subprocess.run(argv, check=True, env=env)


def generate(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    wheels = sorted((root / "dist").glob("okto_nexus_connector_core-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("expected exactly one built Core wheel in dist/")
    env = _clean_environment()
    with tempfile.TemporaryDirectory(prefix="nexus-core-sbom-") as directory:
        temporary = Path(directory)
        target = temporary / "target"
        generator = temporary / "generator"
        venv.create(target, with_pip=True)
        venv.create(generator, with_pip=True)
        _run([str(_python(target)), "-m", "pip", "install",
              "--disable-pip-version-check", str(wheels[0])], env=env)
        # pip bootstraps the isolated environment but is not shipped by the
        # Core wheel. Remove it before inventorying runtime components.
        _run([str(_python(target)), "-m", "pip", "uninstall", "--yes", "pip"],
             env=env)
        _run([str(_python(generator)), "-m", "pip", "install",
              "--disable-pip-version-check", GENERATOR], env=env)
        output.parent.mkdir(parents=True, exist_ok=True)
        _run([str(_python(generator)), "-m", "cyclonedx_py", "environment",
              str(target), "--pyproject", str(root / "pyproject.toml"),
              "--mc-type", "library", "--spec-version", "1.6",
              "--output-format", "JSON", "--output-reproducible",
              "--output-file", str(output)], env=env)
    document = json.loads(output.read_text(encoding="utf-8"))
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.6":
        raise RuntimeError("unexpected SBOM format/version")
    components = document.get("components", [])
    metadata_component = document.get("metadata", {}).get("component")
    if isinstance(metadata_component, dict):
        components = [*components, metadata_component]
    names = {component["name"].lower().replace("_", "-")
             for component in components if isinstance(component, dict)
             and isinstance(component.get("name"), str)}
    if missing := REQUIRED - names:
        raise RuntimeError(f"SBOM missing runtime components: {sorted(missing)}")
    if extra_tools := names & {"pip", "build", "cyclonedx-bom", "setuptools", "wheel"}:
        raise RuntimeError(f"SBOM includes build/generator tools: {sorted(extra_tools)}")
    names_by_ref = {component["bom-ref"]: component["name"].lower().replace("_", "-")
                    for component in components if isinstance(component, dict)
                    and isinstance(component.get("bom-ref"), str)
                    and isinstance(component.get("name"), str)}
    root_ref = metadata_component.get("bom-ref") if isinstance(metadata_component, dict) else None
    roots = [dependency for dependency in document.get("dependencies", [])
             if dependency.get("ref") == root_ref]
    if len(roots) != 1 or not {"jsonschema", "rfc8785"}.issubset(
            {names_by_ref.get(ref) for ref in roots[0].get("dependsOn", [])}):
        raise RuntimeError("SBOM is missing direct Core dependency relationships")
    print(f"CycloneDX 1.6 SBOM verified: {len(names)} components; {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "dist" /
                        "nexus_connector_core.sbom.cdx.json")
    generate(parser.parse_args().output.resolve())
