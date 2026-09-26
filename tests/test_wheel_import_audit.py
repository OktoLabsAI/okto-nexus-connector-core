import pytest
from pathlib import Path
from runpy import run_path

verify_import_boundaries = run_path(
    str(Path(__file__).resolve().parents[1] / "tools" / "verify_wheel.py")
)["verify_import_boundaries"]


def test_wheel_import_audit_accepts_stdlib_core_and_declared_dependencies():
    verify_import_boundaries(
        "import asyncio\nfrom nexus_connector_core.models import CoreError\n"
        "import rfc8785\nfrom jsonschema import Draft202012Validator\n"
        "from .native import registry\n", "sample.py")


@pytest.mark.parametrize("source", [
    "import okto_nexus.domain.harness",
    "from okto_nexus_connector import client",
    "import mcp",
    "from pydantic import BaseModel",
    "import fastapi",
    "import sentence_transformers",
])
def test_wheel_import_audit_rejects_application_and_undeclared_externals(source):
    with pytest.raises(RuntimeError):
        verify_import_boundaries(source, "sample.py")


@pytest.mark.parametrize("source", [
    'import importlib\nimportlib.import_module("okto_nexus.domain.harness")',
    'from importlib import import_module\nimport_module("okto_nexus.application")',
    '__import__("okto_nexus.domain.harness")',
    'from importlib import import_module\nimport_module(module_name)',
    'import sys\nsys.path.insert(0, "../okto_labs_okto_nexus/src")',
    'import importlib.util\nimportlib.util.spec_from_file_location("foreign", "sibling.py")',
])
def test_wheel_import_audit_rejects_dynamic_sibling_loading(source):
    with pytest.raises(RuntimeError):
        verify_import_boundaries(source, "sample.py")


def test_wheel_import_audit_allows_package_relative_registry_load():
    verify_import_boundaries(
        'from importlib import import_module\n'
        'import_module(spec.module, package="nexus_connector_core.native")',
        "nexus_connector_core/native/registry.py")
